"""우리 AI 만들기: 작은 공개 모델을 강의 필기 데이터로 미세조정(QLoRA)하고 Ollama용 GGUF로 내보낸다.

무료 GPU에서 돌린다: Google Colab(T4 16GB) 또는 Kaggle Notebooks(주 30시간). 내 컴퓨터에 GPU가 없어도 된다.
  1) Colab에서 런타임 → 런타임 유형 변경 → T4 GPU
  2) 셀에서:  !pip install -q unsloth
              (train.jsonl, val.jsonl, finetune.py 를 왼쪽 파일 칸에 올린 뒤)
              !python finetune.py --train train.jsonl --val val.jsonl
  3) 끝나면 lecture-notes-gguf/ 폴더의 .gguf 파일과 Modelfile을 내려받는다 (README.md 참고)

기본 바탕 모델: Qwen3-4B-Instruct-2507 (Apache-2.0, 한국어 가능, 4B라 CPU로도 돌릴 만함).
  --base 로 바꿀 수 있다. 라이선스가 상업적 사용을 막는 모델(예: Qwen2.5-3B)은 피한다.
"""

import argparse
import json


def load_rows(path: str) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def main(args: argparse.Namespace) -> None:
    # unsloth를 먼저 불러와야 속도 최적화가 걸린다
    from unsloth import FastLanguageModel
    from unsloth.chat_templates import train_on_responses_only

    from datasets import Dataset
    from trl import SFTConfig, SFTTrainer

    model, tokenizer = FastLanguageModel.from_pretrained(
        model_name=args.base, max_seq_length=args.max_len, load_in_4bit=True,
    )
    model = FastLanguageModel.get_peft_model(
        model, r=args.rank, lora_alpha=args.rank, lora_dropout=0,
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"],
        use_gradient_checkpointing="unsloth", random_state=42,
    )

    def to_text(rows: list[dict]) -> Dataset:
        texts = [tokenizer.apply_chat_template(r["messages"], tokenize=False) for r in rows]
        # 너무 긴 예시는 잘리면 JSON이 깨진 채로 배우므로 뺀다
        texts = [t for t in texts if len(tokenizer(t).input_ids) <= args.max_len]
        return Dataset.from_dict({"text": texts})

    train_rows = load_rows(args.train)
    if args.only:
        train_rows = [r for r in train_rows if r["task"] in args.only.split(",")]
    train = to_text(train_rows)
    val = to_text(load_rows(args.val)) if args.val else None
    print(f"학습 {len(train)}개 · 검증 {len(val) if val else 0}개 · 바탕 {args.base}")

    trainer = SFTTrainer(
        model=model, tokenizer=tokenizer, train_dataset=train, eval_dataset=val,
        args=SFTConfig(
            dataset_text_field="text", max_seq_length=args.max_len,
            per_device_train_batch_size=2, gradient_accumulation_steps=4,
            num_train_epochs=args.epochs, learning_rate=args.lr, lr_scheduler_type="cosine", warmup_ratio=0.05,
            logging_steps=10, eval_strategy="epoch" if val else "no", save_strategy="no",
            optim="adamw_8bit", weight_decay=0.01, seed=42, output_dir="outputs", report_to="none",
        ),
    )
    # 답(assistant) 부분만 배운다: 긴 강의 내용(입력)을 외우지 않게
    trainer = train_on_responses_only(trainer, instruction_part="<|im_start|>user\n", response_part="<|im_start|>assistant\n")
    trainer.train()

    model.save_pretrained("lecture-notes-lora")  # 작은 어댑터만 (다시 이어 학습할 때)
    tokenizer.save_pretrained("lecture-notes-lora")
    # Ollama가 바로 읽는 4비트 GGUF (약 2.5GB)
    model.save_pretrained_gguf("lecture-notes-gguf", tokenizer, quantization_method=args.quant)
    print("끝: lecture-notes-gguf/ 의 .gguf 파일과 이 폴더의 Modelfile로 `ollama create lecture-notes -f Modelfile`")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--train", default="data/train.jsonl")
    parser.add_argument("--val", default="data/val.jsonl")
    parser.add_argument("--base", default="unsloth/Qwen3-4B-Instruct-2507")
    parser.add_argument("--only", default="", help="이 작업만 배우기 (예: annotate). 비우면 전부")
    parser.add_argument("--max-len", type=int, default=4096)
    parser.add_argument("--epochs", type=float, default=2)
    parser.add_argument("--lr", type=float, default=2e-4)
    parser.add_argument("--rank", type=int, default=16)
    parser.add_argument("--quant", default="q4_k_m")
    main(parser.parse_args())
