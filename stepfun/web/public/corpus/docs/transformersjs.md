# Transformers.js 用法要点

Transformers.js 是 Hugging Face 官方的 JavaScript 推理库，目标是让同一份模型在浏览器与 Node 里都能跑。核心入口是 `pipeline()`：第一个参数是任务名，第二个是模型 ID，第三个是运行选项。

做文本嵌入用 `feature-extraction` 任务。加载完成后调用 `extractor(texts, { pooling, normalize })`：`pooling` 决定如何把 token 级向量聚合成句向量，BGE 系列用 `cls`（取 [CLS] 位），Sentence-BERT 类用 `mean`（对 token 取平均）；`normalize` 为 true 时输出单位向量，配合余弦距离使用。

`device` 支持 `webgpu` 与 `wasm`，`dtype` 支持 `fp32`、`fp16`、`q8`、`q4` 等。需要注意后端与精度的搭配：WASM 不支持 fp16，选 fp16 会退化；WebGPU 用 q8 通常比 fp16 慢，因为要额外做反量化。默认值会随设备变化（WebGPU 默认 fp32，WASM 默认 q8），显式指定更可控。

模型文件通过 `progress_callback` 上报下载进度，里面包含 `file`、`progress`、`loaded`、`total`，前端可以直接做成进度条。模型默认缓存在浏览器的 Cache Storage 里，第二次进入页面不再下载；缓存条目带有响应头，可以据此实测"模型实际体积"。

最后是线程与阻塞。WASM 后端支持多线程，但需要页面处于 cross-origin isolated 状态（正确的 COOP/COEP 响应头），否则只有单线程可用；WebGPU 后端是异步提交，但仍应分批并让出事件循环，保证进度条与按钮状态及时刷新。
