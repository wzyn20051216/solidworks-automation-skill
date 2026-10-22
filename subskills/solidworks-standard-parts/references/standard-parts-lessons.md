# 标准件生成实测经验与 API 风险

本文件沉淀直齿轮 / 压缩弹簧 / 滚子链链轮生成中的几何近似边界、SolidWorks COM 接口风险与
真机验收要点。所有几何量以 `scripts/standard_parts_geometry.py` 为准，单位 mm。

## 渐开线直齿轮

- 关键公式：分度圆 d=m·z；基圆 db=d·cos α；齿顶圆 da=d+2·m·(ha*+x)；齿根圆 df=d−2·m·(hf*−x)；
  分度圆齿厚 s=π·m/2+2·x·m·tan α；渐开线函数 inv(α)=tan α−α。
- 半齿角在分度圆处为 π/(2z)，齿廓角度 θ(ρ)=π/(2z)+inv(α)−inv(α_ρ)，α_ρ=acos(db/(2ρ))。
- **根切/尖齿边界**：`is_pointed=True` 表示齿顶隙为 0，齿已尖化，应减小 ha* 或增大 z。齿根圆低于
  基圆时，本实现用径向线近似连接到齿根（不是真实过渡圆角），少齿数或大变位时误差变大，须复核。
- COM 侧用直线段逼近渐开线（默认每侧 12 点）。齿数多、模数小、要啮合仿真时提高 `--samples`。
- 真机验收：重建后 `GetBodies2` 存在实体；数齿数与图纸一致；分度圆直径回读与属性一致。

## 圆柱压缩弹簧

- 关键公式：弹簧指数 C=D/d；刚度 k=G·d⁴/(8·D³·Na)（G 用 MPa=N/mm²，得 N/mm）；实体长度
  closed_ground=Nt·d，closed/open=(Nt+1)·d；有效圈数 closed(_ground)=Nt−2，open=Nt。
- 螺旋中心线始终作为真实 3D 草图曲线创建（证据），再尝试沿其**圆形轮廓扫描**成实体线材。
- **COM 风险（pilot 主因）**：`FeatureManager.InsertProtrusionSwept4` 的参数个数与圆形轮廓选项在
  不同 SolidWorks 版本存在差异；本实现按新版圆形轮廓签名调用，失败时不抛出，降级为
  `representation=helix-centerline`，只交付中心线与 `*_helix_evidence.bmp`。真机若返回该表达，
  须核对签名或改用“螺旋起点法向平面 + 线径圆轮廓 + 扫描”的显式路径。
- 端圈并紧、磨平和压并高度目前不建模，只在属性里记录端型；需要工艺细节时人工建模。
- 真机验收：`representation=swept-solid` 且 `GetBodies2` 存在实体时才导出 STEP；否则明确说明未生成实体。

## 滚子链链轮

- 关键公式（ANSI B29.1 常用近似）：节圆 PD=P/sin(π/N)；齿顶圆 OD=P·(0.6+cot(π/N))；
  齿根圆 RD=PD−Dr；滚子座半径 Rs≈0.505·Dr。
- 齿形为**简化齿形**：滚子座用半圆凹弧、齿顶用相邻节点中点、齿侧用直线连接。适合可视化与
  3D 打印，不代表精确啮合齿形。精确啮合齿形须按 ANSI B29.1 / ISO 606 的座弧+工作弧样条建模并复核。
- 真机验收：数齿数、量节圆/齿顶圆直径与手册一致；滚子座能容纳标称滚子。

## 通用

- 一律 mm 输入，进入 SolidWorks 前用父技能 `mm()` 换算成米。
- 闭合轮廓用 `_common.sketch_closed_profile` 逐段连线；`polygon_is_closed_ccw` 可离线自检朝向。
- 交付一律走 `run_review()`：检查 `expected_outputs_exist`、`previews_not_blank`，并目视复核。
- 新踩坑（版本差异、失败 COM 签名、几何反例）补充到本文件。
