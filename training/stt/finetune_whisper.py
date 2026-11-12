"""우리 받아쓰기 AI: 공개 Whisper를 한국어 강의 말투에 맞게 더 가르친다 (Kaggle 무료 GPU에서).

- 바탕 모델: openai/whisper-small (MIT, 약 250MB로 줄여 쓰면 폰에도 들어간다)
- 데이터: Zeroth-Korean (CC BY 4.0, 한국어 낭독 약 2만 2천 문장) + 있으면 우리 데이터(--extra 폴더의 data.jsonl:
  {"audio": "파일.wav", "text": "정답"} 한 줄씩 — 한국어 강의 시험 녹음, 나중에 AI Hub 강의 음성)
- 학습 전·후를 같은 시험 문장으로 재서(글자 오류율 CER) 정말 좋아졌는지 남긴다
- 결과: whisper-ko-ct2/ (서버의 faster-whisper가 바로 읽는 꼴, int8) · whisper-ko-hf/ (폰용으로 바꿀 원본) · score.txt

사용법: python finetune_whisper.py [--steps 2000] [--base openai/whisper-small] [--extra 폴더]
"""

import argparse
import json
import os
import re
import subprocess
import time
from dataclasses import dataclass

import torch


def norm(text: str) -> str:
    """글자 오류율은 띄어쓰기·문장부호를 빼고 잰다 (한국어는 띄어쓰기가 사람마다 다르다)"""
    return re.sub(r"[^0-9a-zA-Z가-힣]", "", text).lower()


def cer(refs: list[str], hyps: list[str]) -> float:
    import jiwer

    pairs = [(norm(r), norm(h)) for r, h in zip(refs, hyps) if norm(r)]
    return jiwer.cer([r for r, _ in pairs], [h or "∅" for _, h in pairs])


def load_data(extra: str | None):
    from datasets import Audio, concatenate_datasets, load_dataset

    zeroth = load_dataset("Bingsu/zeroth-korean")
    train, test = zeroth["train"], zeroth["test"]
    extra_test = None
    if extra and os.path.exists(os.path.join(extra, "data.jsonl")):
        rows = [json.loads(line) for line in open(os.path.join(extra, "data.jsonl"), encoding="utf-8")]
        rows = [{"audio": os.path.join(extra, r["audio"]), "text": r["text"]} for r in rows if r.get("text")]
        from datasets import Dataset

        ours = Dataset.from_list(rows).cast_column("audio", Audio(sampling_rate=16000))
        ours = ours.train_test_split(test_size=min(200, max(1, len(rows) // 10)), seed=0)
        extra_test = ours["test"]
        train = concatenate_datasets([train.cast_column("audio", Audio(sampling_rate=16000)),
                                      ours["train"].cast_column("audio", Audio(sampling_rate=16000))])
        print(f"우리 데이터 {len(rows)}문장을 더했어요", flush=True)
    train = train.cast_column("audio", Audio(sampling_rate=16000))
    test = test.cast_column("audio", Audio(sampling_rate=16000))
    return train, test, extra_test


@dataclass
class Collator:
    processor: object
    decoder_start: int

    def __call__(self, feats):
        batch = self.processor.feature_extractor.pad([{"input_features": f["input_features"]} for f in feats],
                                                     return_tensors="pt")
        labels = self.processor.tokenizer.pad([{"input_ids": f["labels"]} for f in feats], return_tensors="pt")
        ids = labels["input_ids"].masked_fill(labels.attention_mask.ne(1), -100)
        if (ids[:, 0] == self.decoder_start).all():
            ids = ids[:, 1:]
        batch["labels"] = ids
        return batch


def transcribe(model, processor, ds, limit: int, batch: int = 16) -> tuple[list[str], list[str]]:
    model.eval()
    refs, hyps = [], []
    rows = ds.select(range(min(limit, len(ds))))
    for i in range(0, len(rows), batch):
        part = rows[i:i + batch]
        feats = processor.feature_extractor([a["array"] for a in part["audio"]], sampling_rate=16000,
                                            return_tensors="pt").input_features
        feats = feats.to(model.device, dtype=next(model.parameters()).dtype)
        with torch.no_grad():
            out = model.generate(feats, language="korean", task="transcribe", max_new_tokens=200)
        hyps += processor.batch_decode(out, skip_special_tokens=True)
        refs += part["text"]
    return refs, hyps


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--base", default="openai/whisper-small")
    p.add_argument("--steps", type=int, default=2000)
    p.add_argument("--extra", default=None)
    p.add_argument("--eval", type=int, default=457, help="학습 전·후 시험 문장 수")
    a = p.parse_args()

    from transformers import (Seq2SeqTrainer, Seq2SeqTrainingArguments, WhisperForConditionalGeneration,
                              WhisperProcessor)

    started = time.time()
    processor = WhisperProcessor.from_pretrained(a.base, language="korean", task="transcribe")
    train, test, extra_test = load_data(a.extra)
    print(f"학습 {len(train)}문장 · 시험 {len(test)}문장", flush=True)

    def prep(batch):
        feats = processor.feature_extractor([x["array"] for x in batch["audio"]], sampling_rate=16000).input_features
        return {"input_features": list(feats), "labels": [processor.tokenizer(t).input_ids for t in batch["text"]]}

    report = []
    model = WhisperForConditionalGeneration.from_pretrained(a.base, torch_dtype=torch.float16).to("cuda")
    sets = [("Zeroth 시험", test)] + ([("우리 데이터 시험", extra_test)] if extra_test is not None else [])
    before = {}
    for name, ds in sets:
        refs, hyps = transcribe(model, processor, ds, a.eval)
        before[name] = cer(refs, hyps)
        print(f"학습 전 {name}: CER {before[name]:.2%}", flush=True)
    del model
    torch.cuda.empty_cache()

    model = WhisperForConditionalGeneration.from_pretrained(a.base)
    model.generation_config.language = "korean"
    model.generation_config.task = "transcribe"
    model.generation_config.forced_decoder_ids = None
    model.config.forced_decoder_ids = None
    train.set_transform(prep)
    args = Seq2SeqTrainingArguments(
        output_dir="whisper-ko-run", per_device_train_batch_size=16, learning_rate=1e-5, warmup_steps=200,
        max_steps=a.steps, fp16=True, gradient_checkpointing=True, eval_strategy="no", save_strategy="no",
        logging_steps=50, report_to=[], remove_unused_columns=False, dataloader_num_workers=2,
    )
    trainer = Seq2SeqTrainer(model=model, args=args, train_dataset=train,
                             data_collator=Collator(processor, model.config.decoder_start_token_id))
    trainer.train()

    model = trainer.model.half().to("cuda")
    model.save_pretrained("whisper-ko-hf")
    processor.save_pretrained("whisper-ko-hf")
    for name, ds in sets:
        refs, hyps = transcribe(model, processor, ds, a.eval)
        after = cer(refs, hyps)
        report.append(f"{name}: 글자 오류율 {before[name]:.1%} → {after:.1%} (정확도 약 {1 - before[name]:.1%} → {1 - after:.1%})")
        report += [f"  정답: {r}\n  우리: {h}" for r, h in list(zip(refs, hyps))[:3]]
    report.append(f"바탕 {a.base} · 학습 {len(train)}문장 · {a.steps}걸음 · {(time.time() - started) / 60:.0f}분")
    open("score.txt", "w", encoding="utf-8").write("\n".join(report) + "\n")
    print("\n".join(report), flush=True)

    subprocess.run(["ct2-transformers-converter", "--model", "whisper-ko-hf", "--output_dir", "whisper-ko-ct2",
                    "--quantization", "int8", "--copy_files", "tokenizer.json", "preprocessor_config.json"], check=True)


if __name__ == "__main__":
    main()
