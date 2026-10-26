---
name: cnc-jlc-quote
description: "Guide an authorized JLC CNC China (嘉立创CNC中国站) browser login and quote workflow with iframe modal login, account/password tab, security slider handling, verified STEP upload & parsing, parameter editor modal, lead-time day selection, and reference-estimate classification."
---

# JLC CNC China (嘉立创CNC中国站) 登录与报价工作流规范

本规范适用于嘉立创中国站 CNC 平台（`https://www.jlc-cnc.com` 及报价页面 `https://www.jlc-cnc.com/cncOrder/#/placeOrder`）。
包含完整的受控浏览器登录、安全滑块验证、图纸上传解析、加工参数修改对话框、交期天数选择以及报价读取逻辑。

---

## 一、受控登录流程 (Login Workflow)

1. **访问首页与触发登录**
   - 访问平台首页 `https://www.jlc-cnc.com`（或配置的登录地址）。
   - 定位并点击右上角“登录”按钮（DOM 选择器：`button.login-button` 或 `page.locator("button.login-button").first`）。
   - 注意：首页存在多处包含“登录”文本的节点，必须使用精确类名或 `.first`，避免 Playwright strict mode 冲突。

2. **登录弹窗与 Tab 切换**
   - 点击登录后，页面加载全局全屏登录遮罩 iframe：`iframe#jlc-cas-login-window`。
   - iframe 内容来源于 CAS 统一认证服务（`passport.jlc.com`），内嵌 3 个 Tab 切换项：
     - `扫码登录`（默认微信扫码）
     - `账号登录`（用户名/密码）
     - `手机号登录`（短信验证码）
   - 切换到第 2 个 Tab：“账号登录”：
     - 选择器：`frame.locator('button:has-text("账号登录"), div:has-text("账号登录")').filter({ hasText: "账号登录" }).first`。

3. **凭据填写与提交**
   - 账号输入框：`frame.getByPlaceholder("请输入手机号码 / 客户编号 / 邮箱")`。
   - 密码输入框：`frame.getByPlaceholder("请输入登录密码")`。
   - 提交按钮：`frame.locator("button.submit, button:has-text('登录')").filter({ hasText: "登录" }).first`。
   - 填入对应账号与密码后触发提交。

4. **安全验证滑块处理 (Security Slider)**
   - 提交后，若平台风控触发安全验证，会弹出“安全验证 - 为了您的账号安全，请完成验证 - 请按住滑块，拖动到最右边”。
   - 滑块控件特征：包含 `>>` 拖动按钮与轨道。
   - 处理方式：
     - 系统会将登录会话状态置为 `WAITING_HUMAN`。
     - 前端受控浏览器（`ControlledBrowser.vue` / `AccountLoginDialog.vue`）支持实时画面串流与鼠标拖动交互，用户可在对话框中直接拖动滑块完成验证；完成后点击“验证登录”。

5. **登录状态与身份校验**
   - 登录成功后，受控会话在当前上下文中通过以下只读接口核验用户身份：
     - 门户用户信息：`https://www.jlc-cnc.com/api/cncPortal/login/queryLoginUser`（返回 `casAccountCode`, `customerCode`, `customerName` 等）。
     - CAS SSO 身份信息：`https://passport.jlc.com/api/cas/sso/get-user-info`（POST `{ appId: "CNC_BIZ_GATEWAY" }`，返回 `customerCode`, `customerAccountCode`, `phone` 如 `192****2291`）。
   - 账号匹配规则：
     - 手机号支持前 3 位与后 4 位掩码匹配（如 `19216192291` 匹配 `192****2291`）。
     - 支持精确匹配客户编号（如 `14271345A`）或客户账号（如 `J14378920`）。
     - 身份不符时抛出 `IDENTITY_MISMATCH`，禁止跨账号串号。

---

## 二、跳转报价页面 (Quote Entry Transition)

1. **登录态页面特征**
   - 登录成功后，首页右上角原“注册 / 登录”按钮区域自动变为：
     - `购物车`
     - `在线报价`（`button.order-platform-button`）
     - 用户头像及客户编号（如 `14271345A`）
2. **进入报价页面**
   - 点击右上角“在线报价”按钮，或直接在当前浏览器上下文中导航至报价地址：
     `https://www.jlc-cnc.com/cncOrder/#/placeOrder`。
3. **新手引导遮罩处理**
   - 页面首次加载可能出现引导浮层（如“上传图纸文件 (1/2)”或“新手引导”）：
   - 点击“跳过”（`button:has-text("跳过")`）或“不用了”遮罩，使主界面处于可交互状态。

---

## 三、图纸上传与解析 (Upload CAD & Parsing)

1. **上传区域与文件选择器**
   - 主界面包含“上传图纸”区域及“拖拽或上传图纸文件”按钮（`#uploadFileBut`）。
   - 实际底层原生文件上传控件：`input[type="file"].el-upload__input[name="file"]`。
   - 支持格式：3D 图纸（必须）`.step` / `.stp`；辅助 2D 图纸 `.dwg` / `.dxf` / `.pdf` 或压缩包。
   - 文件限制：单次 ≤20 个，单个文件大小 <100M。
2. **上传操作与解析等待**
   - 通过 Playwright `setInputFiles` 传入验证过的本地 STEP 副本。
   - 上传后进入平台服务端几何解析：
     - 文件越大，特征越复杂，解析等待时间越长（通常数秒至 1~2 分钟不等）。
   - 解析完成后：
     - 列表渲染零件条目，展示零件 3D 渲染缩略图、零件名称（如 `L018-5-M12 (已上传 3D 图纸)`）。
     - 提取几何信息：尺寸（`长*宽*高 mm`）、体积（`mm³`）、表面积（`mm²`）。

---

## 四、加工参数配置修改 (Parameter Editing)

零件上传解析后，默认带有初始参数，必须核对或修改以获取准确报价：

1. **打开参数配置对话框**
   - 点击零件条目中的“修改参数”按钮（选择器：`.change-info.hand`）。
   - 弹出对话框：`.el-dialog.material-dialog`，标题为“选择加工参数”。
2. **各参数字段控制项**
   - **材料 (`* 材料`)**：
     - 分类选项卡：`铝合金` / `塑料` / `铜合金` / `合金钢` / `不锈钢`。
     - 具体材料选项：如 `铝合金-6061`、`铝合金-7075` 等。
   - **表面处理 (`* 表面处理`)**：
     - 模式单选：`需要表面处理（支持多个表面处理）` vs `表面不做处理（会有轻微刀痕，表面略有刮花）`。
     - 若选择需要表面处理：
       - 表面处理工艺下拉框（如 `喷砂+普通阳极氧化`）
       - 颜色下拉框（如 `本色`、`黑色` 等）
       - 光泽单选按钮：`哑光` / `亮光`
   - **加工数量 (`* 加工数量`)**：
     - 步进器/数字输入框，附带 `[数量折扣]` 阶梯说明。
   - **最严公差 (`* 最严公差`)**：
     - 公差标准下拉框（默认 `GB/T 1804-2000 m级`）。
     - 是否需要质检报告单选：`不需要` / `需要`。
   - **外观要求 (`* 外观要求`)**：
     - 下拉选择：`常规外观` 等。
   - **是否有螺纹 (`* 是否有螺纹`)**：
     - 单选按钮：`否` / `是`。
   - **是否有装配关系 (`* 是否有装配关系`)**：
     - 单选按钮：`否` / `是`。
   - **备注**：
     - 特殊加工工艺要求（文本框，0/200 字）。
3. **确认保存参数**
   - 点击对话框右下方“确认”按钮（选择器：`#submit-btn`，按钮文本为 `确  认`）。
   - 确认后对话框关闭，主页面参数信息同步更新，后台自动触发价格重算。

---

## 五、交期天数选择与报价提取 (Lead Time & Quote Extraction)

1. **零件勾选与右侧联动**
   - 勾选零件列表对应行复选框（`.el-checkbox`）。
2. **交期天数选择 (`.delivery-box`)**
   - 右侧交期卡片提供 3 档生产交期选项（单选框）：
     - `加急交期：3个工作日`（附带加急单价/总价）
     - `标准交期：6个工作日`（附带标准单价/总价）
     - `经济交期：11个工作日`（附带经济单价/总价）
   - 根据需求点击对应交期单选框（`.el-radio`），系统总价随之切换并展示预计发货时间（如“今日19点前支付, 预计MM-DD HH:mm前发货”）。
3. **报价数据读取项**
   - 基础金额：零件单价、零件总价。
   - 汇总金额：零件数量（如 `1件 1款`）、税费、总计（含税）、新人券后优惠估算价。
4. **报价结果定级与边界**
   - **REFERENCE_ESTIMATE**：嘉立创页面明确提示“系统预估价”及“系统自动报价仅做参考，最终以人工审核报价为准”，因此属于系统预估价。
   - **人工审核/提交询价**：若图纸文件较大、多零件组合、或超出自动化计价规则，需人工报价或点击“提交询价”。
   - **安全边界**：本流程为报价检索，严禁点击“加入购物车”（`addCarCNC`）、提交订单、填写收货地址发票或进行支付结算。
