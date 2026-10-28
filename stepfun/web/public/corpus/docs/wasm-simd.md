# WASM SIMD 与多线程

WebAssembly 让 C/C++ 编译出的代码以接近原生的速度在浏览器里运行，是端侧推理的兜底方案。两个关键扩展决定了它的性能上限：SIMD 与 threads。

SIMD（`simd128`）允许一条指令处理 128 位数据，也就是 4 个 float32 或 8 个 int16。神经网络的矩阵乘法天然适合向量化，开启 SIMD 后常见加速在 2 到 4 倍之间。ONNX Runtime Web 的 wasm 构建默认启用 SIMD，但会检测运行环境，不支持时回退到普通版本。

多线程依赖 SharedArrayBuffer，而 SharedArrayBuffer 只有在 cross-origin isolated 的页面里才能使用。开启隔离需要服务端返回 `Cross-Origin-Opener-Policy: same-origin` 与 `Cross-Origin-Embedder-Policy: require-corp`，这会连带影响页面引用的第三方资源（它们必须带 CORP 头或使用 CORS）。很多团队为了省事不开隔离，于是 WASM 只能单线程跑。

单线程与四线程的差距在小模型上可能是 2 倍左右，但线程数并非越多越好：线程创建与同步有开销，小 batch 场景下多线程甚至更慢。合理的做法是把线程数限制在 4 左右，并按 batch 大小实测。

对嵌入模型这类 encoder 结构，瓶颈通常在自注意力与 FFN 的矩阵乘法，SIMD 加多线程的收益比较稳定；真正的上限还是模型参数量，所以端侧选型优先看"小模型 + 量化"，而不是指望运行时榨出几倍性能。
