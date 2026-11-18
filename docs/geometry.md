# 渲染原理

程序把三维晶格压到二维屏幕上，用的是**旋转 + 斜投影**两步矩阵乘法。
代码实现在 `src/crystal_viewer/geometry.py`，这里记录公式便于对照。

约定：晶格点按行向量存放，变换写作 `点 @ 矩阵`。

## 旋转矩阵

**α 是旋转角度**

$$
\begin{bmatrix}
    \cos{\alpha} & -\sin{\alpha} & 0 \\
    \sin{\alpha} & \cos{\alpha} & 0 \\
    0 & 0 & 1 \\
\end{bmatrix}
\times
\begin{bmatrix}
    x \\
    y \\
    z \\
\end{bmatrix}=
\begin{bmatrix}
    x\cos\alpha - y\sin\alpha \\
    x\sin\alpha + y\cos\alpha \\
    z
\end{bmatrix}
$$

绕 X、Y 轴的矩阵同理，只是把 $\cos/\sin$ 放到对应的行列位置上：

$$
R_y(\gamma)=
\begin{bmatrix}
    \cos\gamma & 0 & -\sin\gamma \\
    0 & 1 & 0 \\
    \sin\gamma & 0 & \cos\gamma \\
\end{bmatrix}
\qquad
R_x(\beta)=
\begin{bmatrix}
    1 & 0 & 0 \\
    0 & \cos\beta & -\sin\beta \\
    0 & \sin\beta & \cos\beta \\
\end{bmatrix}
$$

每帧把当前姿态右乘一次自旋矩阵，就得到连续的自动旋转效果：

```
姿态 ← 姿态 @ 自旋矩阵
```

角度步长在 `config.yaml` 的 `views[].spin.deg` 里调整，默认 2°（60 fps 下约 3 秒转一圈）。

## 斜投影矩阵

斜投影**不是**直接丢弃 z，而是把 z 折算进 x/y，从而让立方体看起来有纵深。
绕 Y 轴倾斜 30° 的写法：

$$
\begin{bmatrix}
    \cos30° & 0 & -\sin30° \\
    0 & 1 & 0 \\
    \sin30° & 0 & \cos30° \\
\end{bmatrix}
\times
\begin{bmatrix} x \\ y \\ z \end{bmatrix}
=
\begin{bmatrix}
    x\cos30° - z\sin30° \\
    y \\
    x\sin30° + z\cos30° \\
\end{bmatrix}
$$

最后只取结果的 x、y 两个分量作为屏幕坐标，z 分量丢弃。
四个视图分别使用 +30°/−30° 的 Y/X 倾斜，配合不同的初始朝向，
就形成了"同一个晶胞从四个方向环绕"的观感 —— 对应 `config.yaml` 里的
`views[].oblique`。

## 与代码的对应关系

| 数学对象 | 代码 |
| --- | --- |
| $R_x / R_y / R_z$ | `rotation_matrix(axis, deg)` |
| 每帧累乘的自旋 | `ViewGeometry.advance()` |
| 斜投影矩阵 | `SpinStep.from_config(view.oblique)` |
| 投影后取 x、y | `ViewGeometry.projected_xy()` |
