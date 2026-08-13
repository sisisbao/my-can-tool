import streamlit as st
import pandas as pd
import re
import tempfile
import os
import io
import can
from datetime import datetime

# ==================== STREAMLIT 页面设置与标题 (确保显示头正常) ====================
st.set_page_config(page_title="CAN 报文过滤与 UDS 否定响应分析工具", layout="wide")
st.title("🏎️ CAN 报文过滤与 UDS 否定响应分析工具")
st.caption("上传 .txt、.csv、.blf 或 Vector .asc 报文格式，进行 ID 过滤、数据去重，并一键分析 0x7F 否定响应（上下行成对展示）。")

# UDS 服务映射字典
UDS_SERVICES = {
    0x10: "0x10 - DiagnosticSessionControl (诊断会话控制)",
    0x11: "0x11 - ECUReset (ECU复位)",
    0x14: "0x14 - ClearDiagnosticInformation (清除诊断信息)",
    0x19: "0x19 - ReadDTCInformation (读取DTC信息)",
    0x22: "0x22 - ReadDataByIdentifier (通过ID读数据)",
    0x23: "0x23 - ReadMemoryByAddress (通过地址读内存)",
    0x27: "0x27 - SecurityAccess (安全访问)",
    0x2E: "0x2E - WriteDataByIdentifier (通过ID写数据)",
    0x2F: "0x2F - InputOutputControlByIdentifier (输入输出控制)",
    0x31: "0x31 - RoutineControl (例程控制)",
    0x34: "0x34 - RequestDownload (请求下载)",
    0x35: "0x35 - RequestUpload (请求上传)",
    0x36: "0x36 - TransferData (数据传输)",
    0x37: "0x37 - RequestTransferExit (请求退出传输)",
    0x3E: "0x3E - TesterPresent (待机握手)",
    0x85: "0x85 - ControlDTCSetting (控制DTC设置)"
}

# NRC 映射字典
UDS_NRC = {
    0x10: "【0x10】：GeneralReject (通用拒绝)",
    0x11: "【0x11】：ServiceNotSupported (不支持该服务)",
    0x12: "【0x12】：SubFunctionNotSupported (不支持该子功能)",
    0x13: "【0x13】：IncorrectMessageLengthOrInvalidFormat (报文长度或格式错误)",
    0x21: "【0x21】：BusyRepeatRequest (忙，请重复请求)",
    0x22: "【0x22】：ConditionsNotCorrect (条件不满足)",
    0x24: "【0x24】：RequestSequenceError (请求顺序错误)",
    0x31: "【0x31】：RequestOutOfRange (请求超出范围)",
    0x33: "【0x33】：SecurityAccessDenied (安全解锁未通过)",
    0x35: "【0x35】：InvalidKey (密钥无效)",
    0x36: "【0x36】：ExceededNumberOfAttempts (超出解锁尝试次数)",
    0x37: "【0x37】：RequiredTimeDelayNotExpired (防刷写延时未到)",
    0x78: "【0x78】：RequestCorrectlyReceived-ResponsePending (已接收等待响应 - 挂起)",
    0x7E: "【0x7E】：SubFunctionNotSupportedInActiveSession (当前会话不支持此子功能)",
    0x7F: "【0x7F】：ServiceNotSupportedInActiveSession (当前会话不支持此服务)"
}

# 初始化会话状态 (Session State)
if 'processed' not in st.session_state:
    st.session_state['processed'] = False
    st.session_state['raw_count'] = 0
    st.session_state['filtered_count'] = 0
    st.session_state['neg_count'] = 0
    st.session_state['log_txt_data'] = b""
    st.session_state['diag_txt_data'] = b""
    st.session_state['df_details'] = pd.DataFrame()
    st.session_state['df_summary'] = pd.DataFrame()
    st.session_state['df_preview'] = pd.DataFrame()

def clean_and_parse_id(id_str):
    id_str = id_str.strip().lower()
    if not id_str: return None
    try:
        return int(id_str, 16)
    except ValueError:
        return None

def format_can_id(arbitration_id):
    if arbitration_id > 0x7FF:
        return f"{arbitration_id:08X}"
    else:
        return f"{arbitration_id:03X}"

def is_tester_present(msg):
    data = msg['data']
    if not data or len(data) < 2: return False
    can_id = msg['can_id_int']
    is_diag_id = False
    
    if (can_id & 0xFFFF0000) == 0x18DA0000:
        is_diag_id = True
    elif 0x7E0 <= can_id <= 0x7EF or can_id == 0x7DF:
        is_diag_id = True
        
    if not is_diag_id: return False
    if (data[0] & 0xF0) == 0x00:
        length = data[0] & 0x0F
        if length >= 1:
            if data[1] == 0x3E or data[1] == 0x7E: return True
    return False

def parse_asc_or_txt_line(line):
    line = line.strip()
    if not line or any(line.startswith(x) for x in ['//', 'date', 'base']):
        return None
    parts = line.split()
    if len(parts) >= 6:
        try:
            timestamp = float(parts[0])
            channel = f"CAN{parts[1]}"
            raw_id = parts[2]
            if raw_id.lower().endswith('x'): raw_id = raw_id[:-1]
            can_id_int = int(raw_id, 16)
            direction = parts[3]
            if parts[4].lower() == 'd':
                dlc = int(parts[5])
                data_start_idx = 6
            else:
                dlc = int(parts[4])
                data_start_idx = 5
            data_bytes = [int(x, 16) for x in parts[data_start_idx : data_start_idx + dlc]]
            return {
                'timestamp': timestamp, 'channel': channel, 'can_id_int': can_id_int,
                'can_id': format_can_id(can_id_int), 'direction': direction, 'dlc': dlc, 'data': data_bytes
            }
        except: pass
    return None

def load_file(uploaded_file):
    messages = []
    file_extension = os.path.splitext(uploaded_file.name)[1].lower()
    if file_extension in ['.txt', '.asc']:
        string_data = uploaded_file.read().decode('utf-8', errors='ignore')
        for line in string_data.splitlines():
            parsed = parse_asc_or_txt_line(line)
            if parsed: messages.append(parsed)
    elif file_extension == '.blf':
        with tempfile.NamedTemporaryFile(suffix='.blf', delete=False) as temp_file:
            temp_file.write(uploaded_file.read())
            temp_file_path = temp_file.name
        try:
            with can.BLFReader(temp_file_path) as log:
                for msg in log:
                    messages.append({
                        'timestamp': msg.timestamp,
                        'channel': f"CAN{msg.channel + 1}",
                        'can_id_int': msg.arbitration_id,
                        'can_id': format_can_id(msg.arbitration_id),
                        'direction': 'Rx' if msg.is_rx else 'Tx',
                        'dlc': msg.dlc,
                        'data': list(msg.data)
                    })
        finally:
            os.remove(temp_file_path)
    return messages

def analyze_uds_negative_response(msg):
    data = msg['data']
    if not data or len(data) < 3: return None
    if (data[0] & 0xF0) == 0x00:
        length = data[0] & 0x0F
        if length >= 3 and len(data) >= 4 and data[1] == 0x7F: return data[2], data[3]
    if data[0] == 0x00 and len(data) >= 5:
        length = data[1]
        if length >= 3 and data[2] == 0x7F: return data[3], data[4]
    return None

def is_diagnostic_pair(req_id, resp_id):
    if len(req_id) == 8 and len(resp_id) == 8:
        if req_id.startswith("18DA") and resp_id.startswith("18DA"):
            if req_id[4:6] == resp_id[6:8] and req_id[6:8] == resp_id[4:6]: return True
    try:
        if abs(int(resp_id, 16) - int(req_id, 16)) == 8: return True
    except: pass
    return False

def find_matching_request(messages, resp_idx, service_code):
    resp_msg = messages[resp_idx]
    start_idx = max(0, resp_idx - 300)
    for i in range(resp_idx - 1, start_idx - 1, -1):
        req_msg = messages[i]
        if resp_msg['timestamp'] - req_msg['timestamp'] > 2.0: break
        req_data = req_msg['data']
        if not req_data or len(req_data) < 2: continue
        req_service = req_data[1] if (req_data[0] & 0xF0) == 0x00 else (req_data[2] if (req_data[0] & 0xF0) == 0x10 else None)
        if req_service == service_code and is_diagnostic_pair(req_msg['can_id'], resp_msg['can_id']): return req_msg
    return None

# ==================== 侧边栏设置区 ====================
st.sidebar.header("⚙️ 设置与参数")
uploaded_file = st.sidebar.file_uploader("1. 上传报文文件 (支持 .txt, .csv, .blf, .asc)", type=["txt", "csv", "blf", "asc"])

# 当上传新文件时清空旧缓存
if uploaded_file:
    current_file_key = f"file_{uploaded_file.name}_{uploaded_file.size}"
    if st.session_state.get("file_key") != current_file_key:
        st.session_state["file_key"] = current_file_key
        st.session_state['processed'] = False

filter_ids_input = st.sidebar.text_area("2. 过滤 CAN ID (选填，留空则不过滤)", placeholder="例如：0x18DA32F1;0x18daf132")
enable_filtering = st.sidebar.checkbox("开启指定 ID 过滤", value=True)
enable_dedup = st.sidebar.checkbox("删除重复内容 (去重)", value=True)
st.sidebar.caption("💡 去重保护规则：仅在 ID + 精准时间戳 + 数据全等时触发，待机握手（TesterPresent 3E）不受去重影响，全数保留。")
start_btn = st.sidebar.button("⚡ 开始处理数据", type="primary")

# --- 后台逻辑处理触发 ---
if uploaded_file and start_btn:
    with st.spinner("数据深度分析与编译中..."):
        raw_messages = load_file(uploaded_file)
        if not raw_messages:
            st.warning("载入文件为空，分析中止。")
            st.stop()

        target_ids = []
        for x in re.split(r'[,\s\n;，；]+', filter_ids_input):
            val = clean_and_parse_id(x)
            if val is not None: target_ids.append(val)

        # 1. 提取 UDS 诊断对与汇总
        uds_details = []
        summary_map = {} 
        raw_neg_count = 0
        
        for idx, msg in enumerate(raw_messages):
            res = analyze_uds_negative_response(msg)
            if res:
                raw_neg_count += 1
                service_code, nrc_code = res
                req = find_matching_request(raw_messages, idx, service_code)
                
                pair_label = f"诊断对 #{raw_neg_count}"
                service_info = UDS_SERVICES.get(service_code, f"0x{service_code:02X} - Unknown Service")
                nrc_info = UDS_NRC.get(nrc_code, f"【0x{nrc_code:02X}】：Unknown NRC")
                
                summary_key = (service_info, nrc_info)
                summary_map[summary_key] = summary_map.get(summary_key, 0) + 1

                if req:
                    uds_details.append({
                        "事件编号": pair_label,
                        "报文类型": "📤 请求 (Request)",
                        "时间戳": f"{req['timestamp']:.6f}",
                        "通道": req['channel'],
                        "CAN ID": req['can_id'],
                        "DLC": req['dlc'],
                        "数据 (Hex)": " ".join([f"{x:02X}" for x in req['data']]),
                        "服务映射": service_info,
                        "诊断结果/NRC原因": ""
                    })
                uds_details.append({
                    "事件编号": pair_label,
                    "报文类型": "❌ 否定应答 (7F Response)",
                    "时间戳": f"{msg['timestamp']:.6f}",
                    "通道": msg['channel'],
                    "CAN ID": msg['can_id'],
                    "DLC": msg['dlc'],
                    "数据 (Hex)": " ".join([f"{x:02X}" for x in msg['data']]),
                    "服务映射": service_info,
                    "诊断结果/NRC原因": nrc_info
                })

        # 2. 常规报文链过滤
        processed = []
        seen = set()
        for msg in raw_messages:
            if enable_filtering and target_ids and (msg['can_id_int'] not in target_ids):
                continue
            if enable_dedup:
                if is_tester_present(msg):
                    processed.append(msg)
                    continue
                t_str = f"{msg['timestamp']:.6f}"
                d_str = "".join([f"{x:02X}" for x in msg['data']])
                key = (msg['can_id_int'], t_str, d_str)
                if key in seen: continue
                seen.add(key)
            processed.append(msg)

        # 3. 构造导出的文本报告 (转成 bytes 二进制流形式)
        log_txt = io.StringIO()
        report_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_txt.write(f"处理时间: {report_time}\n")
        log_txt.write("=" * 110 + "\n\n")
        l_header = f"{'时间戳':<22} {'通道':<12} {'ID':<15} {'方向':<10} {'DLC':<8} {'数据'}\n"
        log_txt.write(l_header)
        log_txt.write("-" * 110 + "\n")
        for msg in processed:
            d_str = " ".join([f"{x:02X}" for x in msg['data']])
            line = f"{msg['timestamp']:<22.6f} {msg['channel']:<12} {msg['can_id']:<15} {msg['direction']:<10} {msg['dlc']:<8} {d_str}\n"
            log_txt.write(line)

        diag_txt = io.StringIO()
        diag_txt.write(f"UDS 故障诊断对明细报告\n生成时间: {report_time}\n")
        diag_txt.write("=" * 140 + "\n\n")
        d_header = f"{'事件编号':<12} {'报文类型':<25} {'时间戳':<22} {'通道':<10} {'CAN ID':<15} {'DLC':<6} {'数据 (Hex)':<30} {'服务映射'}\n"
        diag_txt.write(d_header)
        diag_txt.write("-" * 140 + "\n")
        for item in uds_details:
            line = f"{item['事件编号']:<12} {item['报文类型']:<25} {item['时间戳']:<22} {item['通道']:<10} {item['CAN ID']:<15} {item['DLC']:<6} {item['数据 (Hex)']:<30} {item['服务映射']}\n"
            diag_txt.write(line)

        # 4. 生成汇总预览表格
        summary_rows = []
        for (srv, nrc), count in summary_map.items():
            summary_rows.append({"服务映射": srv, "诊断结果/NRC原因": nrc, "发生次数": count})
        df_summary = pd.DataFrame(summary_rows)
        if not df_summary.empty:
            df_summary = df_summary.sort_values(by="发生次数", ascending=False)

        # 5. 生成前 100 帧预览明细表格
        preview_list = []
        for msg in processed[:100]:
            preview_list.append({
                "Timestamp": f"{msg['timestamp']:.6f}",
                "Channel": msg['channel'],
                "CAN ID": msg['can_id'],
                "Direction": msg['direction'],
                "DLC": msg['dlc'],
                "Data": " ".join([f"{x:02X}" for x in msg['data']])
            })
        df_preview = pd.DataFrame(preview_list)

        # --- 把所有计算好的数据 转化为 bytes 格式并持久化写入 Session State ---
        st.session_state['processed'] = True
        st.session_state['raw_count'] = len(raw_messages)
        st.session_state['filtered_count'] = len(processed)
        st.session_state['neg_count'] = raw_neg_count
        st.session_state['log_txt_data'] = log_txt.getvalue().encode('utf-8')
        st.session_state['diag_txt_data'] = diag_txt.getvalue().encode('utf-8')
        st.session_state['df_details'] = pd.DataFrame(uds_details)
        st.session_state['df_summary'] = df_summary
        st.session_state['df_preview'] = df_preview

# ==================== 主展示区数据渲染 ====================
if st.session_state['processed'] and uploaded_file:

    # 1. 指标卡片
    c1, c2, c3 = st.columns(3)
    c1.metric("原始报文总数", f"{st.session_state['raw_count']:,}")
    c2.metric("过滤/处理后导出数", f"{st.session_state['filtered_count']:,}")
    c3.metric("UDS 否定响应次数", f"{st.session_state['neg_count']}")

    # 2. 结果下载区 (移除自定义 Key 避免干扰，且直接传递 Bytes 流)
    st.subheader("📥 结果下载")
    d1, d2 = st.columns(2)
    with d1:
        st.download_button(
            label="📂 下载过滤并转化后的 TXT/ASC 文件",
            data=st.session_state['log_txt_data'],
            file_name="filtered_log.txt",
            mime="text/plain"
        )
    with d2:
        st.download_button(
            label="📊 下载 UDS 诊断对照分析报告 (TXT)",
            data=st.session_state['diag_txt_data'],
            file_name="uds_diag_report.txt",
            mime="text/plain"
        )

    # 3. UDS 请求与响应交替明细预览
    st.subheader("📌 UDS 请求与否定响应对应明细 (上下行交替排列)")
    if not st.session_state['df_details'].empty:
        st.dataframe(st.session_state['df_details'], use_container_width=True, hide_index=True)
    else:
        st.info("数据中未检测到 0x7F 否定应答。")

    # 4. 故障汇总区
    st.subheader("🔍 故障汇总 (按 NRC 汇总)")
    if not st.session_state['df_summary'].empty:
        st.dataframe(st.session_state['df_summary'], use_container_width=True, hide_index=True)
    else:
        st.info("无 UDS 故障数据汇总。")

    # 5. 前 100 帧过滤筛选报文预览
    st.subheader("👀 处理后的报文预览 (前 100 条)")
    if not st.session_state['df_preview'].empty:
        st.dataframe(st.session_state['df_preview'], use_container_width=True, hide_index=True)
    else:
        st.info("无报文预览数据")

elif not uploaded_file:
    st.info("💡 请在左侧上传报文文件并点击'开始处理数据'按钮。")