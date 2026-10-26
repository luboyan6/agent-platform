# JLC CNC China (嘉立创CNC中国站) 现场 DOM 与交互凭证

本凭证基于真实环境 live 测试及用户提供的 UI 截图记录，映射嘉立创 CNC 完整的登录、安全验证、图纸解析、参数对话框以及交期选择元素。

---

## 一、登录流程 DOM 元素对照

| 交互步骤 | 页面/容器 | 关键 DOM 选择器 / 属性 | 说明与表现 | 对应截图 |
| :--- | :--- | :--- | :--- | :--- |
| 1. 点击首页登录按钮 | `www.jlc-cnc.com` 顶栏 | `button.login-button` 或 `button:has-text("登录").first` | 蓝色胶囊按钮；注意页面可能存在多处节点，需取 `.first` 避免 strict mode 冲突 | `orca-paste-...-78a165a7-f3f4-40d4-860a-6cfdc068928c.png` |
| 2. 登录弹窗 iframe | 全屏遮罩 | `iframe#jlc-cas-login-window` | 来自 `passport.jlc.com` 的跨域 iframe，样式为 `position: fixed; width: 100%; height: 100%; z-index: 100000` | `orca-paste-...-699a1690-40b4-4e43-b11d-5c88c8613ce2.png` |
| 3. 选择“账号登录” Tab | iframe 内 | `button:has-text("账号登录")` 或 `div:has-text("账号登录")` | 弹窗中 3 个 Tab（扫码登录、账号登录、手机号登录），点击第 2 个 Tab | `orca-paste-...-699a1690-40b4-4e43-b11d-5c88c8613ce2.png` |
| 4. 输入账号 | iframe 内 | `input[placeholder="请输入手机号码 / 客户编号 / 邮箱"]` | 支持手机号、客户编号或邮箱 | `orca-paste-...-699a1690-40b4-4e43-b11d-5c88c8613ce2.png` |
| 5. 输入密码 | iframe 内 | `input[type="password"][placeholder="请输入登录密码"]` | 登录密码输入框 | `orca-paste-...-699a1690-40b4-4e43-b11d-5c88c8613ce2.png` |
| 6. 点击登录提交 | iframe 内 | `button.submit` / `button.base-button.w-full.submit` | 蓝色提交按钮，文本为“登录” | `orca-paste-...-699a1690-40b4-4e43-b11d-5c88c8613ce2.png` |
| 7. 安全验证滑块 | iframe 内浮层 | 提示“请按住滑块，拖动到最右边”，包含滑块轨道与 `>>` 拖动手柄 | 当触发安全风控时出现，受控浏览器置为 `WAITING_HUMAN`，由人工交互或受控画面拖动解决 | `orca-paste-...-a91b948c-1c2f-441f-abaf-ccf8fa9918e7.png` |
| 8. 登录态验证 API 1 | `www.jlc-cnc.com` | `GET https://www.jlc-cnc.com/api/cncPortal/login/queryLoginUser` | 返回 200 JSON：`{ "data": { "casAccountCode": "J14378920", "customerCode": "14271345A", "customerName": "个人" } }`（注意：必须包含 `/api/` 路径） | - |
| 9. 登录态验证 API 2 | `passport.jlc.com` | `POST https://passport.jlc.com/api/cas/sso/get-user-info` 载荷 `{ "appId": "CNC_BIZ_GATEWAY" }` | 返回 200 JSON：`{ "data": { "customerAccountCode": "J14378920", "customerCode": "14271345A", "phone": "192****2291" } }`，支持 11 位手机号掩码核验 | - |

---

## 二、在线报价页面跳转与图纸上传

| 步骤 | 容器 / 区域 | 关键 DOM 选择器 / 属性 | 说明与表现 | 对应截图 |
| :--- | :--- | :--- | :--- | :--- |
| 1. 登录后顶栏 | `www.jlc-cnc.com` | `button.order-platform-button` / 用户头像 | 显示“购物车”、“在线报价”和用户编号 | `orca-paste-...-d6b344d4-fa99-4daf-90dc-6364e0f78d64.png` |
| 2. 在线报价入口 | 链接 / 导航 | `https://www.jlc-cnc.com/cncOrder/#/placeOrder` | 直接跳转报价页 | `orca-paste-...-fef9398c7cdd.png` |
| 3. 新手引导跳过 | 报价页全屏遮罩 | `button:has-text("跳过")` / `button:has-text("不用了")` | 首次进入可能弹出新手提示，需关闭以防遮挡 | - |
| 4. 上传触发按钮 | 上传区域 | `#uploadFileBut`、“拖拽或上传图纸文件” | 界面视觉上传按钮 | `orca-paste-...-fef9398c7cdd.png` |
| 5. 原生文件上传输入项 | 上传区域 | `input[type="file"].el-upload__input[name="file"]` | `accept=".stp,.STP,.step,.STEP,.zip,.ZIP,.rar,.RAR,.pdf,.PDF,.dwg,.DWG,.dxf,.DXF"`，通过 Playwright `setInputFiles` 传入 | `orca-paste-...-fef9398c7cdd.png` |
| 6. 后台几何解析 | 列表渲染中 | 表格出现进度或待解析，大文件耗时更长 | 等待后端解析几何体（尺寸、体积、表面积）完成 | `orca-paste-...-fef9398c7cdd.png` |
| 7. 已解析零件展示 | 零件列表项 | `.tr-content`，展示缩略图、尺寸（如 `28*25*5.47 mm`）、体积（`1856.3 mm³`）、表面积（`1678.73 mm²`） | 零件解析完成，默认带初选参数 | `orca-paste-...-a4d3bfeb-281e-4de7-bd3f-b165b1a5e0ec.png` |

---

## 三、加工参数配置对话框 DOM 元素对照

点击零件行上的“修改参数”（`.change-info.hand`）后弹出对话框 `.el-dialog.material-dialog`（标题“选择加工参数”）：

| 参数项 | DOM 元素 / 交互类型 | 选项值与表现 | 对应截图 |
| :--- | :--- | :--- | :--- |
| **材料分类** | 选项卡 / 列表 | `铝合金`、`塑料`、`铜合金`、`合金钢`、`不锈钢` | `orca-paste-...-4fe92398-f088-4345-8f6e-102aaefc67ef.png` |
| **具体材料** | 单选按钮项 | `铝合金-6061`、`铝合金-7075` 等 | `orca-paste-...-4fe92398-f088-4345-8f6e-102aaefc67ef.png` |
| **表面处理模式** | 卡片单选 | `需要表面处理（支持多个表面处理）` vs `表面不做处理` | `orca-paste-...-4fe92398-f088-4345-8f6e-102aaefc67ef.png` |
| **表面处理工艺** | 下拉框 `el-select` | 如 `喷砂+普通阳极氧化`（默认 100 目） | `orca-paste-...-4fe92398-f088-4345-8f6e-102aaefc67ef.png` |
| **表面处理颜色** | 下拉框 `el-select` | 如 `本色`、`黑色` 等 | `orca-paste-...-4fe92398-f088-4345-8f6e-102aaefc67ef.png` |
| **表面光泽** | 单选框 `el-radio` | `哑光` vs `亮光` | `orca-paste-...-4fe92398-f088-4345-8f6e-102aaefc67ef.png` |
| **加工数量** | 数字步进器 `el-input-number` | 数字输入，包含减号、输入框、加号以及 `[数量折扣]` 查看 | `orca-paste-...-4fe92398-f088-4345-8f6e-102aaefc67ef.png` |
| **最严公差** | 下拉框 `el-select` | 如 `GB/T 1804-2000 m级` | `orca-paste-...-8abe1425-ce21-4b1d-b254-e3e820dcd568.png` |
| **是否需要质检报告** | 单选框 `el-radio` | `不需要` vs `需要` | `orca-paste-...-8abe1425-ce21-4b1d-b254-e3e820dcd568.png` |
| **外观要求** | 下拉框 `el-select` | 如 `常规外观` | `orca-paste-...-8abe1425-ce21-4b1d-b254-e3e820dcd568.png` |
| **是否有螺纹** | 单选框 `el-radio` | `否` vs `是` | `orca-paste-...-8abe1425-ce21-4b1d-b254-e3e820dcd568.png` |
| **是否有装配关系** | 单选框 `el-radio` | `否` vs `是` | `orca-paste-...-8abe1425-ce21-4b1d-b254-e3e820dcd568.png` |
| **参数确认提交按钮** | 按钮控件 | `#submit-btn`（`button.el-button--primary`，文本为 `确  认`） | `orca-paste-...-4fe92398-f088-4345-8f6e-102aaefc67ef.png` |

---

## 四、交期天数选择与价格结算 DOM 元素对照

| 区域 / 项目 | DOM 选择器 / 类名 | 说明与表现 | 对应截图 |
| :--- | :--- | :--- | :--- |
| **零件勾选框** | `tbody .el-checkbox` | 必须勾选已配置的零件行，右侧结算卡片才会激活 | `orca-paste-...-61f9ae80-e858-4d64-b2fd-433ece85a9fd.png` |
| **交期天数卡片** | `.delivery-box` | 包含 3 组带有单选按钮的交期选项：<br>1. `加急交期：3个工作日`（¥316.32）<br>2. `标准交期：6个工作日`（¥179.34）<br>3. `经济交期：11个工作日`（¥162.14） | `orca-paste-...-61f9ae80-e858-4d64-b2fd-433ece85a9fd.png` |
| **交期单选切换** | `.delivery-box .el-radio` | 点击对应 radio 触发即时价格重算，并更新发货承诺时间（如“今日19点前支付,预计10-31 23:00前发货”） | `orca-paste-...-61f9ae80-e858-4d64-b2fd-433ece85a9fd.png` |
| **费用明细项** | 结算信息区域 | 包含：零件数量（如 `2件 1款`）、单价（标注 `系统预估价`）、税费、总计（含税）、券后优惠估算 | `orca-paste-...-61f9ae80-e858-4d64-b2fd-433ece85a9fd.png` |
| **价格定级属性** | 价格文案 | 红色警示文字：“系统自动报价仅做参考，最终以人工审核报价为准” -> 定级为 `REFERENCE_ESTIMATE` | `orca-paste-...-61f9ae80-e858-4d64-b2fd-433ece85a9fd.png` |
| **询价/人工报价** | 按钮控件 | `button:has-text("提交询价")`（多零件/大零件/超出预估规则时使用） | `orca-paste-...-61f9ae80-e858-4d64-b2fd-433ece85a9fd.png` |
| **购物车按钮** | 按钮控件 | `button:has-text("加入购物车")` / `addCarCNC`（报价流程停止边界，严禁自动点击） | `orca-paste-...-61f9ae80-e858-4d64-b2fd-433ece85a9fd.png` |


---

## 五、实测验证样例对照（零件 `L018-5-M12`，2026-10-24 现场实测）

- **零件参数**：
  - 文件名：`L018-5-M12`（3D STEP 图纸）
  - 几何信息：尺寸 `29.4*17*17 mm`，体积 `4314.29 mm³`，表面积 `1983.57 mm²`
  - 加工参数：铝合金-6061，喷砂+普通阳极氧化 - 本色 - 哑光，GB/T 1804-2000 m级 / 常规外观，无螺纹
- **数量 1 件价格**：
  - 单价（系统预估价）：`¥118.45`
  - 总价：`¥118.45`
- **数量 2 件价格（含数量阶梯折扣，对应截图 9）**：
  - 单件单价（系统预估价）：`¥89.67`
  - 零件净总价：`¥179.34`
  - 零件数量：`2件 1款`
  - **加急交期（3个工作日）**：
    - 零件金额：`¥316.32`，税费：`¥41.12`，**总计（含税）：¥357.44**（预计 10-28 23:00 前发货）
  - **标准交期（6个工作日）**：
    - 零件金额：`¥179.34`，税费：`¥23.32`，**总计（含税）：¥202.66**，券后约 `¥152.66`（预计 10-31 23:00 前发货）
  - **经济交期（11个工作日）**：
    - 零件金额：`¥162.14`，税费：`¥21.08`，**总计（含税）：¥183.22**，券后约 `¥152.66`（预计 11-06 23:00 前发货）
  - 现场实测生成的复现截图已保存至：`backend/static/upload/jlc_quote_L018_qty2_verified.png`。
