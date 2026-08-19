# app.py
import streamlit as st
import pandas as pd
from core_parser import process_log_data
from ai_engine import AIManager
from uds_sequence_parser import load_sequence_file, guess_uds_column, parse_uds_sequence
from uds_trajectory_extractor import UDSTrajectoryExtractor
# ==================== 页面基础配置 ====================
st.set_page_config(page_title="UDS AI 智能诊断工作台", layout="wide")

# ==================== 初始化状态机 ====================
if 'current_page' not in st.session_state:
    st.session_state['current_page'] = "数据处理"  # 默认停留在数据处理
if 'processed' not in st.session_state:
    st.session_state['processed'] = False
if 'chat_messages' not in st.session_state:
    st.session_state['chat_messages'] = []

if 'flash_flow_template' not in st.session_state:
    st.session_state['flash_flow_template'] = """1. [10 03] 扩展模式
2. [85 02] 禁用 DTC 设置
3. [28 00] 停掉非诊断报文发送
4. [10 02] 进入编程模式
5. [27 01/02] 安全解锁
6. [34/36/37] 数据传输循环"""

if 'read_flow_template' not in st.session_state:
    st.session_state['read_flow_template'] = """1. [27 03/04] 解锁安全权限
2. [22 F1 90] 读取 VIN 码
3. [22 F1 95] 读取系统供应商 ID"""

# 默认预期流程初始化（如果为空，默认给一个提示）
if 'expected_flow' not in st.session_state:
    st.session_state['expected_flow'] = st.session_state['flash_flow_template']
 
for p in ["DeepSeek", "Kimi (月之暗面)", "Google Gemini"]:
    api_key_name = f"api_key_{p}"
    if api_key_name not in st.session_state:
        st.session_state[api_key_name] = ""

active_page = st.session_state['current_page']

# ==================== CSS 样式注入 (精细化复刻灰色条形目录 + 标志性红色处理按钮) ====================
st.markdown(f"""
    <style>
        /* 仅隐藏右上角的 GitHub 图标链接，保留其他头部元素 */
    [data-testid="stHeaderGitHubLink"] {{
        display: none !important;
    }}
     header a[href*="github"] {{
        display: none !important;
    }}
     a[href*="github"] {{
        display: none !important;
    }}
    /* 侧边栏系统标题格式 */
    .menu-header {{
        font-weight: bold;
        font-size: 1.15rem;
        color: #1A202C;
        margin: 15px 0px 8px 10px;
    }}
    
    /* 屏蔽原生 Streamlit 按钮的默认样式，将其包装为灰色条形 */
    [data-testid="stSidebar"] [data-testid="baseButton-secondary"] {{
        width: 100% !important;
        background-color: transparent !important;
        color: #4A5568 !important; /* 默认深灰文本 */
        border: none !important;
        border-radius: 8px !important; /* 条形平滑圆角 */
        text-align: left !important;
        padding: 10px 14px !important;
        font-size: 0.95rem !important;
        font-weight: normal !important;
        box-shadow: none !important;
        display: flex !important;
        justify-content: flex-start !important;
        align-items: center !important;
        margin: 4px 0px !important;
        transition: all 0.2s ease-in-out;
    }}
    
    /* 悬停时的亮灰色背景 */
    [data-testid="stSidebar"] [data-testid="baseButton-secondary"]:hover {{
        background-color: #EDF2F7 !important;
        color: #2D3748 !important;
    }}

    /* 高亮当前选中的条形目录 */
    [data-testid="stSidebar"] div.element-container:has(#btn_data_process) [data-testid="baseButton-secondary"] {{
        background-color: {"#E2E8F0" if active_page == "数据处理" else "transparent"} !important;
        color: {"#000000" if active_page == "数据处理" else "#4A5568"} !important;
        font-weight: {"bold" if active_page == "数据处理" else "normal"} !important;
    }}
    
    [data-testid="stSidebar"] div.element-container:has(#btn_uds_example) [data-testid="baseButton-secondary"] {{
        background-color: {"#E2E8F0" if active_page == "UDS示例" else "transparent"} !important;
        color: {"#000000" if active_page == "UDS示例" else "#4A5568"} !important;
        font-weight: {"bold" if active_page == "UDS示例" else "normal"} !important;
    }}
    
    [data-testid="stSidebar"] div.element-container:has(#btn_ai_diag) [data-testid="baseButton-secondary"] {{
        background-color: {"#E2E8F0" if active_page == "智能诊断" else "transparent"} !important;
        color: {"#000000" if active_page == "智能诊断" else "#4A5568"} !important;
        font-weight: {"bold" if active_page == "智能诊断" else "normal"} !important;
    }}

    /* 给“开始处理数据”的主按钮和 st.button(..., type="primary") 渲染为红橙色 (图1中标志性Red) */
    div.stButton > button[kind="primary"], [data-testid="baseButton-primary"] {{
        background-color: #FF4D4D !important;
        color: white !important;
        border: none !important;
        font-weight: bold !important;
        width: 100% !important;
        border-radius: 6px !important;
        padding: 10px 20px !important;
        transition: background-color 0.2s ease;
    }}
    div.stButton > button[kind="primary"]:hover, [data-testid="baseButton-primary"]:hover {{
        background-color: #E04343 !important;
        border: none !important;
    }}
    </style>
    """, unsafe_allow_html=True)

# ==================== 左侧自定义条形目录菜单 ====================
with st.sidebar:
    st.markdown('<h2 style="color:#FF5722; padding-left: 10px; margin-bottom:0px; font-weight:bold;">🏎️ UDS Analyzer</h2>', unsafe_allow_html=True)
    st.write("")
    
    st.markdown('<div class="menu-header">系统控制面板 (Automotive)</div>', unsafe_allow_html=True)
    
    st.markdown('<span id="btn_data_process"></span>', unsafe_allow_html=True)
    if st.button("☆   数据处理", use_container_width=True):
        st.session_state['current_page'] = "数据处理"
        st.rerun()
        
    st.markdown('<span id="btn_uds_example"></span>', unsafe_allow_html=True)
    if st.button("☆   UDS示例", use_container_width=True):
        st.session_state['current_page'] = "UDS示例"
        st.rerun()
        
    st.markdown('<span id="btn_ai_diag"></span>', unsafe_allow_html=True)
    if st.button("☆   智能诊断", use_container_width=True):
        st.session_state['current_page'] = "智能诊断"
        st.rerun()
        
    st.markdown("---")
    st.markdown("<div style='padding-left:10px; font-size:0.85rem; color:#A0AEC0;'>"
                "版本: V3.0.4.0 <br> "
                "驱动: Gemini/DeepSeek/Kimi"
                "</div>", unsafe_allow_html=True)

# ==================== 主界面逻辑分流 ====================

# 1. 数据处理页面 (图1的核心工作台)
if st.session_state['current_page'] == "数据处理":
    col_input, col_view = st.columns([1, 2.8])

    with col_input:
        st.markdown("<h3 style='margin-top:0px;'>⚙️ 设置与参数</h3>", unsafe_allow_html=True)
        
        uploaded_file = st.file_uploader(
            "1. 上传报文文件 (支持 .txt, .csv, .blf, .asc, .log)", 
            type=["txt", "csv", "blf", "asc", "log"]
        )
        
        # 预设更合理的过滤 ID 组方便演示（贴合扩展帧诊断 ID 以及常用 11位诊断 ID 格式）
        default_ids = ("0x18DAECF1;0x18DAF1EC;0x18DAECF2;0x18DAF2EC;"
                       "0x18DA00F2;0x18DAF200;0x18DA25F2;0x18DAF225")
        filter_ids_input = st.text_area("2. 过滤 CAN ID (选填，留空则不过滤)", default_ids, height=130)
        
        enable_filtering = st.checkbox("开启指定 ID 过滤", value=True)
        enable_dedup = st.checkbox("删除重复内容 (去重)", value=True)
        
        st.markdown(
            "<p style='color: #718096; font-size: 0.85rem; line-height: 1.4; margin-top: 5px; margin-bottom: 20px;'>"
            "🛡️ 去重保护规则：仅在 ID + 精准时间戳 + 数据全等时触发。待机握手（TesterPresent 3E）不受去重影响，全数保留。"
            "</p>", 
            unsafe_allow_html=True
        )
        
        if st.button("⚡ 开始处理数据", type="primary", use_container_width=True):
            if uploaded_file:
                with st.spinner("正在加载底层解析引擎，数据清洗中..."):
                    try:
                        res = process_log_data(uploaded_file, filter_ids_input, enable_filtering, enable_dedup) 
                        if res and res.get('raw_count', 0) > 0:
                            st.session_state['df_all_uds'] = res.get('df_all_uds')
                            # ================== 核心完美修复逻辑 ==================
                            df_details = res.get('df_details', pd.DataFrame())
                            
                            if not df_details.empty:
                                # 完整版 UDS 服务十六进制字典（支持 0x34 / 0x36 / 0x37 自动翻译翻译）
                                service_hex_map = {
                                    "0x10": "0x10 - DiagnosticSessionControl (诊断会话控制)",
                                    "0x11": "0x11 - ECUReset (ECU复位)",
                                    "0x14": "0x14 - ClearDiagnosticInformation (清除诊断信息)",
                                    "0x19": "0x19 - ReadDTCInformation (读取DTC信息)",
                                    "0x22": "0x22 - ReadDataByIdentifier (通过ID读数据)",
                                    "0x27": "0x27 - SecurityAccess (安全访问)",
                                    "0x28": "0x28 - CommunicationControl (通信控制)",
                                    "0x2E": "0x2E - WriteDataByIdentifier (通过ID写数据)",
                                    "0x31": "0x31 - RoutineControl (例程控制)",
                                    "0x34": "0x34 - RequestDownload (请求下载)",
                                    "0x35": "0x35 - RequestUpload (请求上传)",
                                    "0x36": "0x36 - TransferData (数据传输)",
                                    "0x37": "0x37 - RequestTransferExit (请求退出传输)",
                                    "0x3E": "0x3E - TesterPresent (待机握手)",
                                    "0x85": "0x85 - ControlDTCSetting (控制DTC设置)"
                                }
                                
                                word_to_hex = {
                                    "diagnosticsessioncontrol": "0x10", "ecureset": "0x11",
                                    "cleardiagnosticinformation": "0x14", "readdtcinformation": "0x19",
                                    "readdatabyidentifier": "0x22", "securityaccess": "0x27",
                                    "communicationcontrol": "0x28", "writedatabyidentifier": "0x2E",
                                    "routinecontrol": "0x31", "requestdownload": "0x34",
                                    "requestupload": "0x35", "transferdata": "0x36",
                                    "requesttransferexit": "0x37", "testerpresent": "0x3E",
                                    "controldtcsetting": "0x85"
                                }
                                
                                def format_service_name(srv_val):
                                    srv_str = str(srv_val).strip()
                                    # 1. 尝试从字符串中提取 0xXX 这类的 16 进制串
                                    import re
                                    hex_match = re.search(r'(0x[0-9a-fA-F]{2})', srv_str)
                                    if hex_match:
                                        hex_code = hex_match.group(1).upper().replace("0X", "0x")
                                        if hex_code in service_hex_map:
                                            return service_hex_map[hex_code]
                                    # 2. 模糊尝试英文词匹配
                                    srv_lower = srv_str.lower()
                                    for word, hex_code in word_to_hex.items():
                                        if word in srv_lower:
                                            return service_hex_map[hex_code]
                                    return srv_str

                                col_event = '事件编号'
                                col_type = '报文类型'
                                col_service = '服务映射'
                                col_nrc = '诊断结果/NRC原因'

                                normal_nrc_counts = {}   # 保存常规发生的故障计数 {(service, nrc): count}
                                pending_events = {}      # 保存 78 挂起事件的最终归属 {service: {'success': 0, 'failed': {}}}

                                # 按“事件编号”进行分组扫描
                                for event_id, grp in df_details.groupby(col_event):
                                    # 提取当前事件所属的服务名称
                                    srv_rows = grp[grp[col_service].notna() & (grp[col_service] != '')]
                                    raw_service = srv_rows.iloc[0][col_service] if not srv_rows.empty else "Unknown Service"
                                    service_name = format_service_name(raw_service)
                                    
                                    # 只提取当前组里的“非请求”应答报文
                                    resp_rows = grp[~grp[col_type].astype(str).str.contains('请求|Request', case=False, na=False)]
                                    if resp_rows.empty:
                                        continue

                                    # 检查是否有挂起 (0x78)
                                    has_pending = resp_rows[col_nrc].astype(str).str.contains('78|ResponsePending|Pending', case=False, na=False).any()

                                    if has_pending:
                                        # 排除掉 Pending 状态报文，寻找最终响应
                                        final_responses = resp_rows[~resp_rows[col_nrc].astype(str).str.contains('78|ResponsePending|Pending', case=False, na=False)]
                                        
                                        if not final_responses.empty:
                                            final_row = final_responses.iloc[-1]
                                            final_nrc = str(final_row[col_nrc]).strip()
                                            final_type = str(final_row[col_type]).strip()
                                            
                                            # 判断最终是否是故障（含有【0x 表明是否定响应 NRC）
                                            is_final_fail = "【0x" in final_nrc and not any(ok in final_nrc.lower() for ok in ["success", "成功"])
                                            
                                            if is_final_fail:
                                                if service_name not in pending_events:
                                                    pending_events[service_name] = {'success': 0, 'failed': {}}
                                                pending_events[service_name]['failed'][final_nrc] = pending_events[service_name]['failed'].get(final_nrc, 0) + 1
                                                
                                                # 作为常规业务出错，也计入非 78 故障列表
                                                key = (service_name, final_nrc)
                                                normal_nrc_counts[key] = normal_nrc_counts.get(key, 0) + 1
                                            else:
                                                # 最终代表成功
                                                if service_name not in pending_events:
                                                    pending_events[service_name] = {'success': 0, 'failed': {}}
                                                pending_events[service_name]['success'] += 1
                                        else:
                                            # 如果挂起后没抓到其它回复，默认记为成功 (或悬空状态)
                                            if service_name not in pending_events:
                                                pending_events[service_name] = {'success': 0, 'failed': {}}
                                            pending_events[service_name]['success'] += 1
                                    else:
                                        # 没有 78 伴随，纯粹的直接响应。只统计带有“【0x”且不是 Success 的真实否定否定响应
                                        for _, row in resp_rows.iterrows():
                                            nrc_val = str(row[col_nrc]).strip()
                                            if "【0x" in nrc_val and not any(ok in nrc_val.lower() for ok in ["success", "成功", "pending"]):
                                                key = (service_name, nrc_val)
                                                normal_nrc_counts[key] = normal_nrc_counts.get(key, 0) + 1

                                # 汇总并组装展示数据
                                summary_data = []

                                # 1. 正常业务硬性报错 (排除 Success)
                                for (srv, nrc_desc), count in normal_nrc_counts.items():
                                    summary_data.append({
                                        "服务": srv,
                                        "NRC": nrc_desc,
                                        "次数": count
                                    })

                                # 2. 78 状态汇总 (格式化表现)
                                for srv, stats in pending_events.items():
                                    success_cnt = stats['success']
                                    failed_dict = stats['failed']
                                    total_pending = success_cnt + sum(failed_dict.values())

                                    outcome_parts = []
                                    if success_cnt > 0:
                                        outcome_parts.append(f"成功: {success_cnt}次")
                                    if failed_dict:
                                        fail_parts = [f"失败( {n} ): {c}次" for n, c in failed_dict.items()]
                                        outcome_parts.append(", ".join(fail_parts))
                                    
                                    outcome_desc = ", ".join(outcome_parts)
                                    nrc_label = f"【0x78】: ResponsePending (最终响应 -> {outcome_desc})"

                                    summary_data.append({
                                        "服务": srv,
                                        "NRC": nrc_label,
                                        "次数": total_pending
                                    })

                                # 升维 DataFrame，根据次数降序排列展示
                                df_summary_res = pd.DataFrame(summary_data)
                                if not df_summary_res.empty:
                                    res['df_summary'] = df_summary_res.sort_values(by="次数", ascending=False)
                                else:
                                    res['df_summary'] = pd.DataFrame(columns=["服务", "NRC", "次数"])
                            else:
                                res['df_summary'] = pd.DataFrame(columns=["服务", "NRC", "次数"])
                            # ======================================================================
                            
                            st.session_state.update(res)
                            st.session_state['processed'] = True
                            st.success("🎉 数据转换完成！结果在右侧同步输出。")
                        else:
                            st.error("❌ 解析失败：未在文件中匹配到任何有效的 CAN 报文数据。请确认工具是否适配您的文件列格式。")
                    except Exception as e:
                        st.error(f"❌ 处理数据时发生运行错误: {str(e)}")
            else:
                st.warning("⚠️ 请先加载一笔原始总线报文文件数据。")
        
        
    with col_view:
        # 右侧规范主标题
        st.markdown("<h2 style='margin-top:0px; margin-bottom: 2px;'>🏎️ CAN 报文过滤与 UDS 否定响应分析工具</h2>", unsafe_allow_html=True)
        st.markdown("<p style='color: #718096; font-size: 0.95rem; margin-top:0px;'>上传 .txt、.csv、.blf 或 Vector .asc 报文格式，进行 ID 过滤、数据去重，并一键分析 0x7F 否定响应 (上下行成对展示)。</p>", unsafe_allow_html=True)
        st.write("---")

        if st.session_state['processed']:
            # 大数字指标栏 (Metric)
            m1, m2, m3 = st.columns(3)
            with m1:
                st.markdown("<p style='color:#718096; font-size: 0.95rem; margin-bottom:0px;'>原始报文总数</p>", unsafe_allow_html=True)
                st.markdown(f"<h1 style='font-size: 2.8rem; font-weight: bold; margin-top:0px; color:#2D3748;'>{st.session_state.get('raw_count', 0):,}</h1>", unsafe_allow_html=True)
            with m2:
                st.markdown("<p style='color:#718096; font-size: 0.95rem; margin-bottom:0px;'>过滤/处理后导出数</p>", unsafe_allow_html=True)
                st.markdown(f"<h1 style='font-size: 2.8rem; font-weight: bold; margin-top:0px; color:#2D3748;'>{st.session_state.get('filtered_count', 0):,}</h1>", unsafe_allow_html=True)
            with m3:
                st.markdown("<p style='color:#718096; font-size: 0.95rem; margin-bottom:0px;'>UDS 否定响应次数</p>", unsafe_allow_html=True)
                st.markdown(f"<h1 style='font-size: 2.8rem; font-weight: bold; margin-top:0px; color:#2D3748;'>{st.session_state.get('neg_count', 0):,}</h1>", unsafe_allow_html=True)
            
            st.write("")
            
            # 下载下载区 (对应图1中的“成果栏”)
            st.markdown("### 📥 结果下载", unsafe_allow_html=True)
            d1, d2 = st.columns(2)
            with d1:
                st.download_button(
                    "📁 下载过滤并转化后的 TXT/ASC 文件", 
                    st.session_state['log_txt_bytes'], 
                    "filtered_log.txt",
                    use_container_width=True
                )
            with d2:
                st.download_button(
                    "📊 下载 UDS否定应答明细 (TXT)", 
                    st.session_state['diag_txt_bytes'], 
                    "uds_neg_response_detail.txt",
                    use_container_width=True
                )
            
            st.write("---")
            
            # 请求与否定应答明细表格
            st.markdown("<h4>📌 UDS 请求与否定响应对应明细 (上下行交替排列)</h4>", unsafe_allow_html=True)
            if not st.session_state['df_details'].empty:
                st.dataframe(st.session_state['df_details'], use_container_width=True, hide_index=True)
            else:
                st.info("当前筛选和数据流中没有解析捕获到 7F 否定应答序列。")
                
            st.write("")
            
            # 汇总异常
            st.markdown("<h4>🔍 故障汇总 (按 NRC 汇总)</h4>", unsafe_allow_html=True)
            if not st.session_state['df_summary'].empty:
                st.dataframe(st.session_state['df_summary'], use_container_width=True, hide_index=True)
            else:
                st.info("无 NRC 异常统计。")

            st.write("")
            
            # 数据预览
            st.markdown("<h4>👀 处理后的报文预览 (前 100 条)</h4>", unsafe_allow_html=True)
            if not st.session_state['df_preview'].empty:
                st.dataframe(st.session_state['df_preview'], use_container_width=True, hide_index=True)
        else:
            st.info("📥 请在左侧上传报文数据，配置完成参数后，点击左下角红色按钮「⚡ 开始处理数据」启动分析面板。")

# 2. UDS 服务顺序示例页面
elif st.session_state['current_page'] == "UDS示例":
    st.header("📑 UDS 服务顺序配置中心")
    st.info("💡 您可以在下方编辑标准流程，点击“应用到诊断”后，AI 将以此为准进行逻辑校验。")
    
    tab_a, tab_b, tab_import = st.tabs(["🔥 标准刷写流程", "🔍 参数读取流程", "📥 导入解析 Excel"])
    
    with tab_a:
        # 使用 text_area 让用户可以编辑
        edited_flash = st.text_area(
            "编辑标准刷写步骤", 
            value=st.session_state['flash_flow_template'], 
            height=250,
            key="flash_editor"
        )
        if st.button("🚀 将此流程应用到智能诊断", key="apply_flash"):
            st.session_state['expected_flow'] = edited_flash
            st.success("已同步！现在可以去「智能诊断」页面开始分析了。")
            st.balloons()
            
    with tab_b:
        edited_read = st.text_area(
            "编辑参数读取步骤", 
            value=st.session_state['read_flow_template'], 
            height=250,
            key="read_editor"
        )
        if st.button("🚀 将此流程应用到智能诊断", key="apply_read"):
            st.session_state['expected_flow'] = edited_read
            st.success("已同步！预期流程已更新。")
            st.balloons()
            
    # app.py 中的 tab_import 逻辑
    with tab_import:
        st.markdown("#### 📂 上传序列定义文件")
        uds_file = st.file_uploader("支持 .xlsx, .xls, .csv 格式", type=["xlsx", "xls", "csv"], key="uds_flow_uploader")
        
        # 1. 解析导入逻辑（仅在上传文件时显示）
        if uds_file:
            try:  # <--- 这是【外层 try】
                # 明确驱动并读取
                df_ex = load_sequence_file(uds_file)
                
                # 诊断信息：显示总行数，防止因预览产生误解
                st.write(f"📊 文件读取成功：共检测到 **{len(df_ex)}** 行数据")
                
                # 不再只显示 head(5)，改用高度固定的完整预览
                st.dataframe(df_ex, height=250, use_container_width=True)
                
                candidate_cols = list(df_ex.columns)
                guess_idx = guess_uds_column(df_ex)
                
                sel_col = st.selectbox("请确认包含 UDS 指令（如 10 03）的列：", candidate_cols, index=guess_idx)

                if st.button("🚀 识别并导入至智能诊断", type="primary"):
                    with st.spinner("正在解析业务链路..."):
                        try:  # <--- 这是【内层 try】
                            parser_result = parse_uds_sequence(df_ex, sel_col)
                            if isinstance(parser_result, tuple):
                                flow_chain_str = parser_result[0]
                                metadata_table_str = parser_result[1]
                            else:
                                flow_chain_str = parser_result
                                metadata_table_str = ""
                            st.session_state['expected_flow'] = flow_chain_str
                            st.session_state['expected_flow_metadata'] = metadata_table_str
                            st.success("✅ 识别成功！已同步至智能诊断面板。")
                            st.balloons()
                        except Exception as e:  # <--- 对应【内层 try】
                            st.error(f"文件解析失败: {e}")
                            
            except Exception as e:  # <--- 【核心修复：补上了外层 try 对应的 except！】
                st.error(f"❌ 读取 Excel 文件失败: {e}")
                

        # 2. 【核心修改点】无论是否正在上传，只要 session_state 里有值，就保持显示
        st.markdown("---")
        st.subheader("📌 当前生效的预期流程预览")
        
        # 确保初始化
        if 'expected_flow' not in st.session_state:
            st.session_state['expected_flow'] = ""
            
        if st.session_state['expected_flow']:
            # 使用文本编辑框展示它，用户也可以当场手动微调，内容实时写回
            edited_flow = st.text_area(
                "内存中已加载的流程序列如下，您在此处进行的调整也会被诊断引用：",
                value=st.session_state['expected_flow'],
                height=180
            )
            # 实时回写，防止失去同步
            st.session_state['expected_flow'] = edited_flow
            st.info("💡 此流程判定链将作为「智能诊断」大模型的判断基准。")
 
        else:
            st.warning("⚠️ 当前内存中尚无有效的预期 UDS 流程，请在上方上传并识别文件。")

   

# 3. 大模型对话分析页面
elif st.session_state['current_page'] == "智能诊断":
    st.header("🤖 智能 AI 协同诊断助手")
    
    if not st.session_state['processed']:
        st.error("❌ 尚未在内存中发现已解析的数据。请先去左侧菜单切换至「数据处理」并解析文件项目。")
    else:
        # 1. AI 参数配置区
        ai_col1, ai_col2, ai_col3 = st.columns(3)
        provider = ai_col1.selectbox("AI 供应商", ["DeepSeek", "Kimi (月之暗面)", "Google Gemini"])
        
        # 【核心修改】：通过指定 key 将输入值直接绑定到 session_state 对应的服务商键上
        api_key_state_key = f"api_key_{provider}"
        api_key = ai_col2.text_input(
            f"{provider} API Key", 
            value=st.session_state.get(api_key_state_key, ""),
            type="password",
            key=api_key_state_key
        )
        # provider = ai_col1.selectbox("AI 供应商", ["DeepSeek", "Kimi (月之暗面)", "Google Gemini"])
        # api_key = ai_col2.text_input(f"{provider} API Key", type="password")
        
        model_options = {
            "DeepSeek": ["deepseek-chat", "deepseek-coder"],
            "Kimi (月之暗面)": ["moonshot-v1-8k", "moonshot-v1-32k"],
            "Google Gemini": ["gemini-1.5-flash", "gemini-1.5-pro"]
        }
        selected_model = ai_col3.selectbox("具体模型选择", model_options[provider])

        # 2. 预期流程输入区
        expected_flow = st.text_area(
            "当前采用的预期 UDS 流程", 
            value=st.session_state.get('expected_flow', ""),
            height=200,
            key="diag_flow_area",
            help="此内容同步自「UDS示例」页面，您也可以在此临时修改。"
        )
        st.session_state['expected_flow'] = expected_flow
            
        if 'last_ai_response' not in st.session_state:
            st.session_state['last_ai_response'] = ""
        if 'chat_messages' not in st.session_state:
            st.session_state['chat_messages'] = []
            
        # === 优化后的预览区：点击后再计算，避免频繁转圈 ===
        st.markdown("---")
        with st.expander("🛠️ 诊断前预检：查看 AI 即将接收的“提纯后”报文轨道", expanded=False):
            if 'df_all_uds' in st.session_state and not st.session_state['df_all_uds'].empty:
                
                # 预先检查是否有缓存好的提纯轨迹
                if 'cached_local_trace' not in st.session_state:
                    st.session_state['cached_local_trace'] = ""

                # 只有点击这个按钮，才会触发解析逻辑，节省 CPU
                if st.button("🔍 生成/刷新提纯预览"):
                    with st.spinner("本地引擎正在极速扫描总线报文..."):
                        # 执行耗时操作
                        st.session_state['cached_local_trace'] = UDSTrajectoryExtractor.get_token_friendly_markdown(
                            st.session_state['df_all_uds']
                        )
                
                # 如果已经生成过，就显示出来
                if st.session_state['cached_local_trace']:
                    st.info("💡 这是本地从报文中提纯出的 UDS 指令流：")
                    st.text_area(
                        "提纯后的有效 UDS 指令流 (预览)", 
                        value=st.session_state['cached_local_trace'], 
                        height=300,
                        key="trace_preview_display"
                    )
                    line_count = len(st.session_state['cached_local_trace'].splitlines())
                    st.caption(f"提纯后共计 {line_count} 行有效记录。")
                else:
                    st.write("点击上方按钮，即可在本地提纯报文轨迹（不消耗 Token）。")
            else:
                st.warning("⚠️ 尚未检测到已处理的数据，请先在「数据处理」页面点击开始处理。")
        st.markdown("---")
            
        # 触发诊断分析
        if st.button("🔍 启动 AI 对比分析", type="primary"):
            if not api_key:
                st.warning("🔑 请先填写并配置 API Key，然后再向诊断大模型发起请求！")
            else:
                st.session_state['chat_messages'].append({"role": "user", "content": "启动一键总线差异比对分析诊断。"})
                with st.spinner("🚀 本地引擎正在结合 Excel 规约与总线日志进行AI深度诊断..."):
                    try:
                        # 1. 核心改进：直接提取全局总线动作轨迹字符串（不限制行数，秒级处理完百万数据）
                        data_source = st.session_state.get('df_all_uds', st.session_state['df_preview'])
                        actual_trace_full_str = UDSTrajectoryExtractor.get_token_friendly_markdown(
                            data_source
                        )
                        protocol_metadata = st.session_state.get('expected_flow_metadata', "未解析到详细的 Excel 规约信息。")

                        # 2. 格式化 7F 否定应答明细
                        diag_str = st.session_state['df_details'].to_string(index=False) if not st.session_state['df_details'].empty else "日志中未检测到 7F 否定应答（无异常中断）。"
                        
                        # 3. 提取 NRC 故障统计
                        summary_df = st.session_state.get('df_summary', pd.DataFrame())
                        summary_str = summary_df.to_string(index=False) if not summary_df.empty else "无 NRC 异常统计。"

                        # 4. 构建精简但全局的诊断 Payload（要求输出 Markdown 对照表）
                        prompt_payload = (
                            f"你是一位精通汽车 UDS (ISO 14229) 诊断协议和 CAN 报文分析的资深专家。\n"
                            f"请通过严格比对【预期定义流程】与本地解包出的【实际动作链】，找出漏做、提前跳转等偏离错误，并提供技术报告。\n\n"
                            f"📋 [预期的刷写/诊断定义流程]:\n"
                            f"```markdown\n{expected_flow}\n```\n\n"
                            f"📖 [预期定义流程的详细规约与备注手册] (包含每个步骤的具体名称、应答与备注参数定义):\n"
                            f"```markdown\n{protocol_metadata}\n```\n\n"
                            f"🚗 [从全量日志中还原的实际执行顺序 (本地已聚合压缩)]:\n"
                            f"```markdown\n{actual_trace_full_str}\n```\n\n"
                            f"⚠️ [实际诊断报错对汇总 (7F 应答)]:\n"
                            f"```text\n{diag_str}\n```\n\n"
                            f"📊 [报文内发现的 NRC 状态分布统计]:\n"
                            f"```text\n{summary_str}\n```\n\n"
                            f"--------------------------------------------------\n"
                            f"请严格依据以上经过全量扫描的数据，输出如下结构的分析报告：\n\n"
                            f"### 📊 预期与实际执行对比对照表格\n"
                            f"分析实际捕获的报文流，直接输出一个 Markdown 对比表格：\n"
                            f"| 预期步骤 | 实际执行状态 | 结论 | 备注分析 |\n"
                            f"| :--- | :--- | :--- | :--- |\n"
                            f"规则：\n"
                            f"- 如果实际轨迹中有对应指令，结论为 '✅完成'；\n"
                            f"- 如果实际轨迹中缺失，结论为 '❌缺失'；\n"
                            f"- 如果实际轨迹中有 7F 报错，结论为 '⚠️异常'，并在备注中解释相应 NRC 的具体物理含义（例如 78-Pending, 22-ConditionsNotCorrect 等）。\n\n"
                            f"- 【重要豁免规则】：如果备注中提示有 '先收到0x78 Pending后成功' 或者是 7F 78 之后最终有正响应成功，这属于标准的 UDS 等待过渡，该步骤最终判定为成功，结论**必须**显示为 '✅完成'（而非 '⚠️异常'），并在备注中说明‘曾触发 78 Pending 挂起，最终成功完成’。\n\n"
                            f"### 🔍 深度偏差定位与错误机制分析\n"
                            f"1. **执行吻合度评估**：实际运行步伐是否与预期全匹配？中途是否已经到达了预期流程的末尾（例如 37 退出传输是否确实被触发运行了）？\n"
                            f"2. **偏离点定位及错误机制解耦**：如果中途有报错 NRC。分析报错的 SID 及其环境，以及发生此 NRC 代码的底层软件或硬件诱因（如电压不足、安全解锁超时等）。\n"
                            f"3. **关键参数校验**：分析实际运行中的关键服务（如 34 下载请求, 31 例程控制）的参数是否符合手册备注定义的范围。\n"
                            f"4. **异常机制解耦**：如果发生 7F 报错，结合报错时请求的参数（如地址是否越界）分析诱因。\n"
                            f"5. **闭环排查指导**：基于报文细节，给出下一步测试建议。"
                        )
                        
                        # 调用对应的 AI 模块
                        if provider == "DeepSeek":
                            res_text = AIManager.call_deepseek(api_key, selected_model, prompt_payload, [])
                        elif provider == "Kimi (月之暗面)":
                            res_text = AIManager.call_kimi(api_key, selected_model, prompt_payload, [])
                        else:
                            res_text = AIManager.call_gemini(api_key, selected_model, prompt_payload)
                        
                        st.session_state['last_ai_response'] = res_text
                        st.rerun()
                    except Exception as e:
                        st.error(f"调用失败：{e}")

        # --- 4. 报告常驻显示区 (只显示一次，永远在对话框上方) ---
        if st.session_state['last_ai_response']:
            st.markdown("---")
            st.subheader("📝 智能诊断报告（最新生成）")
            
            # 显示报告内容
            st.markdown(st.session_state['last_ai_response'])
            
            # 报告下载按钮（明确位置）
            st.download_button(
                label="📥 导出诊断报告 (Markdown)",
                data=st.session_state['last_ai_response'],
                file_name="UDS_Report.md",
                mime="text/markdown",
                key="download_main_report"
            )

            # =========================================================
            # 对话追问窗口
            # =========================================================
            st.markdown("---")
            st.subheader("💬 专家追问与细节下钻")

            # 渲染历史追问（跳过主报告内容）
            for msg in st.session_state['chat_messages']:
                with st.chat_message(msg["role"]):
                    st.markdown(msg["content"])

            # 对话输入框
            if prompt := st.chat_input("针对报告结果进行技术追问..."):
                # 展示并保存用户问题
                st.session_state['chat_messages'].append({"role": "user", "content": prompt})
                with st.chat_message("user"):
                    st.markdown(prompt)

                # 调用 AI 进行回答
                with st.chat_message("assistant"):
                    try:
                        # --- 核心修改点：在追问上下文中注入【协议备注元数据】 ---
                        # 获取之前存入的 Excel 备注信息
                        protocol_metadata = st.session_state.get('expected_flow_metadata', '（未提供详细协议备注）')
                        
                        # 构建增强版上下文，让 AI 拥有“查阅手册”的能力
                        context_prompt = (
                            f"你是一位正在协助分析 UDS 日志的专家。请结合以下背景信息回答用户问题：\n\n"
                            f"📖 [背景 1：预期协议规约手册(含备注细节)]:\n{protocol_metadata}\n\n"
                            f"📝 [背景 2：之前生成的诊断报告]:\n{st.session_state['last_ai_response']}\n\n"
                            f"❓ [当前用户追问]: {prompt}\n\n"
                            f"请注意：如果用户询问报文中的特定字节含义（如地址、大小），请务必查阅背景1中的“备注”列进行解答。"
                        )
                        
                        # 调用 AI 进行回答 (保持原有驱动逻辑不变)
                        if provider == "DeepSeek":
                            ans = AIManager.call_deepseek(api_key, selected_model, context_prompt, st.session_state['chat_messages'][:-1])
                        elif provider == "Kimi (月之暗面)":
                            ans = AIManager.call_kimi(api_key, selected_model, context_prompt, st.session_state['chat_messages'][:-1])
                        else:
                            # Gemini 或其他模型
                            ans = AIManager.call_gemini(api_key, selected_model, context_prompt)
                            
                        st.markdown(ans)
                        st.session_state['chat_messages'].append({"role": "assistant", "content": ans})
                    except Exception as e:
                        st.error(f"对话异常：{e}")
            
