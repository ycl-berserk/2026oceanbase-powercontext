# WebGPU 基础

WebGPU 是浏览器的新一代图形与计算 API，取代 WebGL。它直接映射到 Vulkan、Metal、D3D12 这类现代图形接口，提供显式的资源管理与计算着色器能力。对 AI 推理来说，最关键的是 compute shader：可以用 WGSL 写通用计算，把矩阵乘法、归一化、激活函数放到 GPU 上并行执行。

使用流程大致是：`navigator.gpu.requestAdapter()` 拿到适配器，`adapter.requestDevice()` 拿到设备，然后创建 buffer、写数据、提交 compute pipeline、读回结果。注意两点：写入 buffer 要用 `queue.writeBuffer`，读回需要 `mapAsync` 加 `getMappedRange`，这些操作都是异步的。

可用性检测要写得保守：`navigator.gpu` 可能不存在（旧浏览器、被策略禁用），`requestAdapter()` 也可能返回 null（无可用 GPU、驱动被拉黑）。因此不能只在启动时判断一次就到处假设可用，应该把"探测结果 + 失败原因"一起呈现，方便用户理解为什么退到了 WASM。

在 Windows 上，Chrome/Edge 的 WebGPU 依赖 D3D12 与显卡驱动；在 Linux 上需要 Vulkan；某些虚拟机或远程桌面环境里适配器不可用。这也是端侧应用必须实现 WASM 降级路径的现实原因。
