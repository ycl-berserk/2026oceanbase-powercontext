#!/usr/bin/env bash
# 可选：把嵌入模型预下载到 web/public/models，便于离线演示 / 内网测评。
#   bash scripts/fetch-model.sh
#   HF_ENDPOINT=https://hf-mirror.com bash scripts/fetch-model.sh   # 国内镜像
set -euo pipefail
MODEL="${MODEL:-Xenova/bge-small-zh-v1.5}"
BASE="${HF_ENDPOINT:-https://huggingface.co}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEST="${1:-$HERE/../web/public/models}/$MODEL"
mkdir -p "$DEST/onnx"

for f in config.json tokenizer.json tokenizer_config.json special_tokens_map.json \
         onnx/model.onnx onnx/model_fp16.onnx onnx/model_quantized.onnx; do
  if [ -s "$DEST/$f" ]; then
    echo "✓ 已存在 $f"
    continue
  fi
  echo "↓ $f"
  curl -fL --retry 3 --retry-delay 2 "$BASE/$MODEL/resolve/main/$f" -o "$DEST/$f"
done

echo
du -sh "$DEST"
echo "模型已就位：$DEST（应用会自动检测并改为本地加载，不再访问 Hugging Face）"
