"""학습한 Whisper(whisper-ko-hf 폴더)를 서버의 faster-whisper가 읽는 꼴(CTranslate2, int8)로 바꾼다.

저장된 폴더에 tokenizer.json · preprocessor_config.json 이 없으면(라이브러리 버전에 따라 이름이 달라진다) 바탕 모델에서 받아 채운다.
사용법: python convert_ct2.py whisper-ko-hf whisper-ko-ct2 [openai/whisper-small]
"""

import os
import shutil
import subprocess
import sys


def main(src: str, out: str, base: str = "openai/whisper-small") -> None:
    from huggingface_hub import hf_hub_download

    for name in ("tokenizer.json", "preprocessor_config.json"):
        if not os.path.exists(os.path.join(src, name)):
            shutil.copy(hf_hub_download(base, name), os.path.join(src, name))
            print(f"{name}: 바탕 모델({base})에서 가져옴")
    shutil.rmtree(out, ignore_errors=True)
    subprocess.run(["ct2-transformers-converter", "--model", src, "--output_dir", out, "--quantization", "int8",
                    "--copy_files", "tokenizer.json", "preprocessor_config.json"], check=True)
    print("변환 끝:", sorted(os.listdir(out)))


if __name__ == "__main__":
    main(*sys.argv[1:4])
