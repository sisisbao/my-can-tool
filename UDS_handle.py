import streamlit as st
import pandas as pd
import re
import tempfile
import os
import io
import can

# UDS 服务映射字典
UDS_SERVICES = {
    0x10: "DiagnosticSessionControl (诊断会话控制)",
    0x11: "ECUReset (ECU复位)",
    0x14: "ClearDiagnosticInformation (清除诊断信息)",
    0x19: "ReadDTCInformation (读取DTC信息)",
    0x22: "ReadDataByIdentifier (通过ID读数据)",
    0x23: "ReadMemoryByAddress (通过地址读内存)",
    0x27: "SecurityAccess (安全访问)",
    0x2E: "WriteDataByIdentifier (通过ID写数据)",
    0x2F: "InputOutputControlByIdentifier (输入输出控制)",
    0x31: "RoutineControl (例程控制)",
    0x34: "RequestDownload (请求下载)",
    0x35: "RequestUpload (请求上传)",
    0x36: "TransferData (数据传输)",
    0x37: "RequestTransferExit (请求退出传输)",
    0x3E: "TesterPresent (待机握手)",
    0x85: "ControlDTCSetting (控制DTC设置)"
}

# NRC (Negative Response Code) 映射字典
UDS_NRC = {
    0x10: "GeneralReject (通用拒绝)",
    0x11: "ServiceNotSupported (不支持该服务)",
    0x12: "SubFunctionNotSupported (不支持该子功能)",
    0x13: "IncorrectMessageLengthOrInvalidFormat (报文长度或格式错误)",
    0x21: "BusyRepeatRequest (忙，请重复请求)",
    0x22: "ConditionsNotCorrect (条件不满足)",
    0x24: "RequestSequenceError (请求顺序错误)",
    0x31: "RequestOutOfRange (请求超出范围)",
    0x33: "SecurityAccessDenied (安全解锁未通过)",
    0x35: "InvalidKey (密钥无效)",
    0x36: "ExceededNumberOfAttempts (超出解锁尝试次数)",
    0x37: "RequiredTimeDelayNotExpired (防刷写延时未到)",
    0x78: "RequestCorrectlyReceived-ResponsePending (已接收等待响应 - 挂起)",
    0x7E: "SubFunctionNotSupportedInActiveSession (当前会话不支持此子功能)",
    0x7F: "ServiceNotSupportedInActiveSession (当前会话不支持此服务)"
}

def parse_asc_or_txt_line(line):
    """
    解析单行 ASC / TXT 格式 CAN 数据，支持 Vector 标准格式
    """
    line = line.strip()
    if not line or line.startswith('//') or line.startswith('date') or line.startswith('base'):
        return None
    
    parts = line.split()
    if len(parts) >= 6:
        try:
            timestamp = float(parts[0])
            channel = f"CAN{parts[1]}"
            
            # 解析 ID 并剥离末尾的 x
            raw_id = parts[2]
            if raw_id.lower().endswith('x'):
                raw_id = raw_id[:-1]
            can_id = raw_id.upper().replace('0X', '')
            
            direction = parts[3]
            
            if parts[4].lower() == 'd':
                dlc = int(parts[5])
                data_start_idx = 6
            else:
                dlc = int(parts[4])
                data_start_idx = 5
                
            data_bytes = [int(x, 16) for x in parts[data_start_idx : data_start_idx + dlc]]
            
            return {
                'timestamp': timestamp,
                'channel': channel,
                'can_id': can_id,
                'direction': direction,
                'dlc': dlc,
                'data': data_bytes
            }
        except Exception:
            pass
            
    # 匹配简单 "ID Data" 格式
    match = re.search(r'^(0x)?[0-9a-fA-F]+\s+([0-9a-fA-F]{2}\s*)+$', line)
    if match:
        try:
            tokens = line.split()
            can_id = tokens[0].upper().replace('0X', '')
            data_bytes = [int(x, 16) for x in tokens[1:]]
            return {
                'timestamp': 0.0,
                'channel': 'CAN1',
                'can_id': can_id,
                'direction': 'Rx',
                'dlc': len(data_bytes),
                'data': data_bytes
            }
        except Exception:
            pass
            
    return None

def load_file(uploaded_file):
    """
    解析各种类型的报文文件
    """
    messages = []
    file_extension = os.path.splitext(uploaded_file.name)[1].lower()
    
    if file_extension in ['.txt', '.asc']:
        string_data = uploaded_file.read().decode('utf-8', errors='ignore')
        for line in string_data.splitlines():
            parsed = parse_asc_or_txt_line(line)
            if parsed:
                messages.append(parsed)
                
    elif file_extension == '.csv':
        df = pd.read_csv(uploaded_file)
        col_map = {col.lower(): col for col in df.columns}
        
        time_col = next((col_map[k] for k in ['timestamp', 'time', '时间'] if k in col_map), None)
        id_col = next((col_map[k] for k in ['id', 'can_id', 'arbitration_id', '标识符'] if k in col_map), None)
        dlc_col = next((col_map[k] for k in ['dlc', 'len', 'length', '长度'] if k in col_map), None)
        data_col = next((col_map[k] for k in ['data', 'payload', '数据'] if k in col_map), None)
        chan_col = next((col_map[k] for k in ['channel', '通道'] if k in col_map), 'channel')
        dir_col = next((col_map[k] for k in ['direction', 'dir', 'rx/tx', '方向'] if k in col_map), 'direction')

        for _, row in df.iterrows():
            try:
                raw_id = str(row[id_col]) if id_col else '0'
                if raw_id.lower().endswith('x'):
                    raw_id = raw_id[:-1]
                can_id = hex(int(raw_id, 16) if raw_id.lower().startswith('0x') else int(raw_id)).upper().replace('0X', '')
                
                data_str = str(row[data_col]) if data_col else ''
                raw_data = data_str.replace(' ', '').replace(',', '')
                data_bytes = [int(raw_data[i:i+2], 16) for i in range(0, len(raw_data), 2)]
                
                messages.append({
                    'timestamp': float(row[time_col]) if time_col else 0.0,
                    'channel': str(row[chan_col]) if time_col and chan_col in row else 'CAN1',
                    'can_id': can_id,
                    'direction': str(row[dir_col]) if time_col and dir_col in row else 'Rx',
                    'dlc': int(row[dlc_col]) if dlc_col else len(data_bytes),
                    'data': data_bytes
                })
            except Exception:
                continue
                
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
                        'can_id': hex(msg.arbitration_id).upper().replace('0X', ''),
                        'direction': 'Rx' if msg.is_rx else 'Tx',
                        'dlc': msg.dlc,
                        'data': list(msg.data)
                    })
        finally:
            os.remove(temp_file_path)
            
    return messages

def analyze_uds_negative_response(msg):
    """
    检查消息是否代表 UDS 否定响应 (7F)
    """
    data = msg['data']
    if not data or len(data) < 3:
        return None
    
    # 场景1：普通 ISO-TP 诊断单帧 (data[0] 长度低4位，data[1] == 0x7F)
    if (data[0] & 0xF0) == 0x00:
        length = data[0] & 0x0F
        if length >= 3 and len(data) >= 4 and data[1] == 0x7F:
            return data[2], data[3]  # Service ID, NRC

    # 场景2：CAN FD 诊断单帧 (data[0] == 0x00, data[1] 长度, data[2] == 0x7F)
    if data[0] == 0x00 and len(data) >= 5:
        length = data[1]
        if length >= 3 and data[2] == 0x7F:
            return data[3], data[4]  # Service ID, NRC
            
    return None

def is_diagnostic_pair(req_id, resp_id):
    """
    判断两个 ID 是否属于匹配的 UDS 请求和应答
    """
    # 1. 29位扩展地址匹配 (例如 18DA00F1 和 18DAF100)
    if len(req_id) == 8 and len(resp_id) == 8:
        if req_id.startswith("18DA") and resp_id.startswith("18DA"):
            req_da, req_sa = req_id[4:6], req_id[6:8]
            resp_da, resp_sa = resp_id[4:6], resp_id[6:8]
            if req_da == resp_sa and req_sa == resp_da:
                return True
                
    # 2. 11位标准地址匹配 (通常应答ID - 请求ID == 8, 比如 7E0 和 7E8)
    try:
        req_val = int(req_id, 16)
        resp_val = int(resp_id, 16)
        if abs(resp_val - req_val) == 8:
            return True
    except ValueError:
        pass
        
    return False

def find_matching_request(messages, resp_idx, service_code):
    """
    从当前否定响应向前搜索对应的诊断请求报文
    """
    resp_msg = messages[resp_idx]
    resp_time = resp_msg['timestamp']
    resp_id = resp_msg['can_id']
    
    # 向前搜索最多 300 条或 2.0 秒内的报文
    start_idx = max(0, resp_idx - 300)
    
    # 优先找严格匹配 ID 和服务码的报文
    for i in range(resp_idx - 1, start_idx - 1, -1):
        req_msg = messages[i]
        if resp_time - req_msg['timestamp'] > 2.0:
            break
            
        req_data = req_msg['data']
        if not req_data or len(req_data) < 2:
            continue
            
        # 提取候选请求的 UDS 业务码
        req_service = None
        if (req_data[0] & 0xF0) == 0x00:  # 单帧
            req_service = req_data[1]
        elif (req_data[0] & 0xF0) == 0x10: # 首帧
            req_service = req_data[2]
            
        if req_service == service_code and is_diagnostic_pair(req_msg['can_id'], resp_id):
            return req_msg
            
    # 次优策略：只根据服务码查找同通道距离最近的主动请求
    for i in range(resp_idx - 1, start_idx - 1, -1):
        req_msg = messages[i]
        if resp_time - req_msg['timestamp'] > 2.0:
            break
            
        req_data = req_msg['data']
        if not req_data or len(req_data) < 2:
            continue
            
        req_service = None
        if (req_data[0] & 0xF0) == 0x00:
            req_service = req_data[1]
        elif (req_data[0] & 0xF0) == 0x10:
            req_service = req_data[2]
            
        if req_service == service_code and req_msg['channel'] == resp_msg['channel']:
            return req_msg
            
    return None

# ==================== STREAMLIT 界面部分 ====================
st.set_page_config(page_title="CAN 诊断与报文过滤分析工具", layout="wide")

st.title("🚗 CAN 报文过滤与 UDS 否定响应分析工具")
st.markdown("上传 **.txt**、**.csv**、**.blf** 或 Vector **.asc** 报文格式，进行 ID 过滤、数据去重，并一键分析 0x7F 负响应（上下行成对展示）。")

# 侧边控制面板
st.sidebar.header("🔧 设置与参数")
uploaded_file = st.sidebar.file_uploader(
    "1. 上传报文文件 (支持 .txt, .csv, .blf, .asc)", 
    type=["txt", "csv", "blf", "asc"]
)

filter_ids_input = st.sidebar.text_area(
    "2. 过滤 CAN ID (选填，留空则不过滤)", 
    placeholder="例如: 7E8, 7E9, 18DAF110\n支持逗号、空格或换行分隔"
)

# 报文过滤去重选项
enable_filtering = st.sidebar.checkbox("开启指定 ID 过滤", value=False)
enable_dedup = st.sidebar.checkbox("删除重复内容 (去重)", value=True)
dedup_strategy = st.sidebar.selectbox(
    "去重依据",
    ["CAN ID + DLC + Data (最常用)", "CAN ID 唯一 (保留首次出现)"]
)

# 开始处理按钮
start_btn = st.sidebar.button("⚡ 开始处理数据", type="primary")

if uploaded_file is not None and start_btn:
    with st.spinner("🚀 文件分析中，请稍候..."):
        # 1. 加载数据
        try:
            raw_messages = load_file(uploaded_file)
        except Exception as e:
            st.error(f"解析文件出错: {str(e)}")
            st.stop()
            
        if not raw_messages:
            st.warning("未能在文件中解析到任何有效的 CAN 消息，请检查报文格式是否规范。")
            st.stop()

        # 整理过滤的 ID 列表
        target_ids = []
        if enable_filtering and filter_ids_input.strip():
            target_ids = [x.upper().replace('0X', '') for x in re.split(r'[,\s\n]+', filter_ids_input) if x]

        # 2. UDS 扫描诊断分析与请求关联（拆分为“上下”双行结构）
        uds_table_rows = []
        event_counter = 1
        raw_neg_response_count = 0
        
        for idx, msg in enumerate(raw_messages):
            uds_res = analyze_uds_negative_response(msg)
            if uds_res:
                raw_neg_response_count += 1
                service_code, nrc_code = uds_res
                
                # 寻找关联请求报文
                req_msg = find_matching_request(raw_messages, idx, service_code)
                service_name = UDS_SERVICES.get(service_code, "Unknown Service")
                nrc_desc = UDS_NRC.get(nrc_code, "Unknown NRC")
                
                # 构造【上行】：诊断请求行
                if req_msg:
                    uds_table_rows.append({
                        "事件编号": f"诊断对 #{event_counter}",
                        "报文类型": "📤 UDS 请求 (Request)",
                        "时间戳": f"{req_msg['timestamp']:.6f}",
                        "通道": req_msg['channel'],
                        "CAN ID": req_msg['can_id'],
                        "DLC": req_msg['dlc'],
                        "数据 (Hex)": " ".join([f"{x:02X}" for x in req_msg['data']]),
                        "服务映射": f"0x{service_code:02X} - {service_name}",
                        "诊断结果/NRC原因": ""
                    })
                else:
                    uds_table_rows.append({
                        "事件编号": f"诊断对 #{event_counter}",
                        "报文类型": "❓ 未找到匹配的请求报文",
                        "时间戳": "—",
                        "通道": msg['channel'],
                        "CAN ID": "—",
                        "DLC": "—",
                        "数据 (Hex)": "—",
                        "服务映射": f"0x{service_code:02X} - {service_name}",
                        "诊断结果/NRC原因": ""
                    })
                
                # 构造【下行】：否定响应行
                uds_table_rows.append({
                    "事件编号": f"诊断对 #{event_counter}",
                    "报文类型": "❌ 否定应答 (7F Response)",
                    "时间戳": f"{msg['timestamp']:.6f}",
                    "通道": msg['channel'],
                    "CAN ID": msg['can_id'],
                    "DLC": msg['dlc'],
                    "数据 (Hex)": " ".join([f"{x:02X}" for x in msg['data']]),
                    "服务映射": f"0x{service_code:02X} - {service_name}",
                    "诊断结果/NRC原因": f"【0x{nrc_code:02X}】: {nrc_desc}"
                })
                
                event_counter += 1
        
        # 3. 执行过滤与去重导出
        processed_messages = []
        seen_keys = set()
        
        for msg in raw_messages:
            msg_id = msg['can_id']
            # ID 过滤
            if enable_filtering and target_ids and (msg_id not in target_ids):
                continue
                
            # 去重处理
            if enable_dedup:
                if dedup_strategy == "CAN ID + DLC + Data (最常用)":
                    data_str = "".join([f"{x:02X}" for x in msg['data']])
                    key = (msg_id, msg['dlc'], data_str)
                else: # CAN ID 唯一
                    key = msg_id
                    
                if key in seen_keys:
                    continue
                seen_keys.add(key)
                
            processed_messages.append(msg)
            
        # 页面统计展示
        col1, col2, col3 = st.columns(3)
        col1.metric("原始报文总数", f"{len(raw_messages):,}")
        col2.metric("过滤/处理后导出数", f"{len(processed_messages):,}")
        col3.metric("UDS 否定响应次数", f"{raw_neg_response_count:,}")
        
        # --- 创建下载数据文件 ---
        # 导出 ASC/TXT 报文
        output_txt = io.StringIO()
        output_txt.write("// Generated by CAN Analyst Tool\n")
        output_txt.write("// Format: Time Channel ID Dir d DLC Data...\n")
        for msg in processed_messages:
            data_str = " ".join([f"{x:02X}" for x in msg['data']])
            output_txt.write(
                f"{msg['timestamp']:.6f} {msg['channel']} {msg['can_id']} {msg['direction']} d {msg['dlc']} {data_str}\n"
            )
        
        # 导出 uds records csv (上下行格式)
        uds_df = pd.DataFrame(uds_table_rows)
        csv_buffer = io.StringIO()
        uds_df.to_csv(csv_buffer, index=False)
        
        # UI 提供下载按钮
        st.subheader("📥 结果下载")
        dl_col1, dl_col2 = st.columns(2)
        with dl_col1:
            st.download_button(
                label="📁 下载过滤并转化后的 TXT/ASC 文件",
                data=output_txt.getvalue(),
                file_name="processed_can_log.asc",
                mime="text/plain",
            )
        with dl_col2:
            st.download_button(
                label="📊 下载 UDS 诊断对照分析报告 (CSV)",
                data=csv_buffer.getvalue(),
                file_name="uds_neg_responses_report.csv",
                mime="text/csv",
            )

        # 4. 可视化界面展示
        st.subheader("📌 UDS 请求与否定响应对应明细 (上下行交替排列)")
        if uds_table_rows:
            # 渲染成交互式表格，便于工程师按事件分组上下对照查看
            st.dataframe(uds_df, use_container_width=True, hide_index=True)
            
            # NRC 提取聚合汇总表
            st.subheader("🔍 故障汇总 (按 NRC 汇总)")
            # 过滤只显示响应行的原因在统计中
            neg_only_df = uds_df[uds_df["报文类型"] == "❌ 否定应答 (7F Response)"]
            summary_df = neg_only_df.groupby(["服务映射", "诊断结果/NRC原因"]).size().reset_index(name="发生次数")
            st.table(summary_df.sort_values(by="发生次数", ascending=False))
        else:
            st.success("🎉 未扫描到任何 UDS 否定响应 (0x7F)！系统运行良好。")
            
        # 4.2 过滤后的报文预览
        st.subheader("👀 处理后的报文预览 (前 100 条)")
        preview_data = []
        for msg in processed_messages[:100]:
            preview_data.append({
                "Timestamp": f"{msg['timestamp']:.6f}",
                "Channel": msg['channel'],
                "CAN ID": msg['can_id'],
                "Direction": msg['direction'],
                "DLC": msg['dlc'],
                "Data": " ".join([f"{x:02X}" for x in msg['data']])
            })
        st.dataframe(pd.DataFrame(preview_data), use_container_width=True)

elif uploaded_file is None:
    st.info("💡 请在左侧侧边栏中上传您的 CAN 报文文件 (支持 .txt, .csv, .blf, .asc) 开始分析工作。")