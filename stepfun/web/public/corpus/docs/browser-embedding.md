# 浏览器端 embedding 推理

把嵌入模型搬到浏览器里跑，收益很直接：文档内容不用上传，向量化不依赖网络，隐私与延迟都可控。代价是要在用户设备上下载模型、占用内存和算力，并且要面对浏览器运行时的兼容性问题。

主流方案是 Transformers.js。它把 Hugging Face 上的模型转成 ONNX 格式，用 ONNX Runtime Web 在前端执行，API 与 Python 的 transformers 高度相似：`pipeline('feature-extraction', model, { device, dtype })` 之后直接喂文本就能拿到向量。

浏览器里有两个执行后端。WebGPU 走 GPU，适合矩阵乘法密集的 transformer 推理，吞吐通常是 WASM 的数倍；WASM 走 CPU，兼容性最好，几乎所有现代浏览器都能跑。工程上应当优先尝试 WebGPU，失败时自动降级到 WASM，并在界面上明确告诉用户当前用的是哪个后端——否则用户会困惑为什么同样操作快慢差很多。

几个实践要点：模型要选端侧友好的小模型（几千万参数级别），并用 INT8 或 FP16 量化压缩体积；推理要分批（batch）执行，既提高吞吐也避免长时间阻塞主线程；首帧包含图优化与管线编译，必须和后续请求分开计时，否则延迟数据会失真。
