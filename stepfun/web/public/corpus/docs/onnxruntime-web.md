# ONNX Runtime Web 与执行后端

ONNX Runtime Web（ORT Web）是 Transformers.js 底层的推理引擎，负责把 ONNX 计算图调度到不同的执行后端：`wasm`（WebAssembly）、`webgpu`（WebGPU）、以及历史上的 `webgl`。它自带算子实现与图优化，模型作者只需要导出 ONNX。

WASM 后端的性能取决于三个因素：SIMD 支持、线程数、以及算子是否命中优化实现。SIMD 让一条指令处理多个数据，通常带来数倍加速；多线程需要 SharedArrayBuffer，而后者要求页面开启 cross-origin isolation。在普通页面里，WASM 会退化成单线程，这是端侧推理常见的性能上限来源。

WebGPU 后端把算子编译成 GPU 着色器执行，适合大矩阵乘法。它的开销集中在首次编译管线（首帧很慢），之后单次推理明显快于 WASM。工程上要做"预热"：模型加载完成后先跑一次短文本，把首帧成本从用户的第一次真实请求里挪走。

选择后端时不要只看峰值速度。WebGPU 在小 batch、短文本场景可能因为提交开销而不占优；WASM 在多线程开启后也能接近。合理的做法是：默认 WebGPU，检测失败或性能不达预期时降级到 WASM，并把当前后端与耗时暴露在界面上，让评测数据自己说话。
