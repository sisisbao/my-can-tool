import pandas as pd
import re
import tempfile
import os
import io
import can
# 请确保你的项目目录下有 constants.py，并且包含 UDS_SERVICES, UDS_NRC, format_can_id
from constants import UDS_SERVICES, UDS_NRC, format_can_id

# ==================== 基础辅助工具 ====================
def clean_and_parse_id(id_str):
    id_str = id_str.strip().lower()
    if not id_str: return None
    try:
        if id_str.startswith('0x'): return int(id_str, 16)
        return int(id_str, 16)
    except ValueError: return None
    
def format_msg_line(msg):
    """通用报文行格式输出"""
    d_str = " ".join([f"{x:02X}" for x in msg['data']])
    # 优先使用解析时记录的原原始时间戳字符串，保持格式一致
    ts_str = msg.get('timestamp_str')
    if ts_str is not None:
        return f"{ts_str:<22} {msg['channel']:<12} {msg['can_id']:<15} {msg['dlc']:<8} {d_str}"
    return f"{msg['timestamp']:<22.6f} {msg['channel']:<12} {msg['can_id']:<15} {msg['dlc']:<8} {d_str}"

def is_tester_present(msg):
    """【关键修复】：判断是否为 3E 握手报文（防止被错误去重）"""
    data = msg['data']
    if not data or len(data) < 2: return False
    can_id = msg['can_id_int']
    # 判定是否为诊断 ID 范围
    is_diag_id = (can_id & 0xFFFF0000) == 0x18DA0000 or (0x7E0 <= can_id <= 0x7EF) or (can_id == 0x7DF)
    if not is_diag_id: return False
    # 单帧(PCI=0) 且 SID=0x3E
    if (data[0] & 0xF0) == 0x00 and len(data) >= 2:
        if data[1] == 0x3E or data[1] == 0x7E: return True
    return False

# ==================== 格式专用解析函数 ====================

def parse_vector_asc(text_data):
    """
    通用型 Vector ASC 解析器
    逻辑：在行中搜索 Rx/Tx 标志位，动态定位 ID 和时间戳
    """
    messages = []
    for line in text_data.splitlines():
        line_s = line.strip()
        # 跳过空行和文件头
        if not line_s or any(line_s.startswith(x) for x in ['//', 'date', 'base', 'Begin', 'End', 'Statistic']):
            continue
        
        parts = line_s.split()
        if len(parts) < 5: continue
        
        try:
            # 找到 Rx 或 Tx 的索引作为锚点
            dir_idx = -1
            for i, p in enumerate(parts):
                if p.upper() in ['RX', 'TX', 'CANFD']: # 适配部分带 CANFD 标签的行
                    dir_idx = i
                    if p.upper() == 'CANFD': # 如果是CANFD，真正的方向可能在下一位
                         if i+1 < len(parts) and parts[i+1].upper() in ['RX', 'TX']:
                             dir_idx = i+1
                    break
            
            if dir_idx < 2: continue # 锚点前必须有 ID 和 时间戳相关信息

            # 1. 提取方向
            direction = parts[dir_idx]
            
            # 2. 提取 ID (锚点前一位)
            id_raw = parts[dir_idx - 1].lower().replace('x', '')
            if id_raw.startswith('0x'):
                can_id_int = int(id_raw, 16)
            else:
                can_id_int = int(id_raw, 16)
            
            # 3. 提取通道 (锚点前二位)
            channel = f"CAN{parts[dir_idx - 2]}"
            
            # 4. 提取时间戳
            ts_candidate = parts[dir_idx - 3]
            try:
                timestamp_val = float(ts_candidate)
            except:
                timestamp_val = float(parts[dir_idx - 4])
                ts_candidate = parts[dir_idx - 4]

            # 5. 定位 DLC 和数据段
            next_idx = dir_idx + 1
            if next_idx < len(parts) and parts[next_idx].lower() in ['d', 'brs', 'canfd']:
                next_idx += 1
            
            dlc = int(parts[next_idx])
            data_start = next_idx + 1
            data = [int(x, 16) for x in parts[data_start : data_start + dlc]]
            
            messages.append({
                'timestamp': timestamp_val,
                'timestamp_str': ts_candidate,
                'channel': channel,
                'can_id_int': can_id_int,
                'can_id': format_can_id(can_id_int),
                'direction': direction,
                'dlc': dlc,
                'data': data
            })
        except:
            continue
    return messages

def parse_custom_log(string_data):
    """适配 10:05:24:0580 Rx 1 0x18DA... 格式"""
    messages = []
    for line in string_data.splitlines():
        line = line.strip()
        if not line or line.startswith('*'): continue
        parts = line.split()
        if len(parts) < 7: continue
        try:
            time_str = parts[0]
            if ':' not in time_str: continue 
            
            t_parts = time_str.replace('.', ':').split(':')
            h, m, s = int(t_parts[0]), int(t_parts[1]), int(t_parts[2])
            ms = int(t_parts[3]) if len(t_parts) > 3 else 0
            ms_div = 10**len(t_parts[3]) if len(t_parts) > 3 else 1000
            ts = h * 3600 + m * 60 + s + (ms / ms_div)
            
            dir_idx = -1
            for i in range(len(parts)):
                if parts[i].upper() in ['RX', 'TX']:
                    dir_idx = i; break
            
            if dir_idx == -1: continue
            
            can_id_int = int(parts[dir_idx + 2], 16) if '0x' in parts[dir_idx + 2] else int(parts[dir_idx + 2], 16)
            if parts[3].startswith('0x'):
                can_id_int = int(parts[3], 16)
                dlc = int(parts[5])
                data_idx = 6
            else:
                can_id_int = int(parts[dir_idx + 2], 16)
                dlc = int(parts[dir_idx + 4])
                data_idx = dir_idx + 5

            data = [int(x, 16) for x in parts[data_idx : data_idx + dlc]]
            messages.append({
                'timestamp': ts, 'timestamp_str': time_str,
                'channel': f"CAN{parts[dir_idx+1]}", 'can_id_int': can_id_int,
                'can_id': format_can_id(can_id_int), 'direction': parts[dir_idx],
                'dlc': dlc, 'data': data
            })
        except: continue
    return messages

def parse_blf(content):
    messages = []
    with tempfile.NamedTemporaryFile(suffix='.blf', delete=False) as tmp:
        tmp.write(content)
        tmp_path = tmp.name
    try:
        with can.BLFReader(tmp_path) as log:
            for msg in log:
                messages.append({
                    'timestamp': msg.timestamp, 'timestamp_str': None,
                    'channel': f"CAN{msg.channel + 1}", 'can_id_int': msg.arbitration_id,
                    'can_id': format_can_id(msg.arbitration_id),
                    'direction': 'Rx' if msg.is_rx else 'Tx', 
                    'dlc': msg.dlc, 'data': list(msg.data)
                })
    finally:
        if os.path.exists(tmp_path): os.remove(tmp_path)
    return messages

def parse_csv_generic(content_input):
    """Vehicle Spy 3 适配"""
    try:
        if isinstance(content_input, bytes):
            try:
                content_str = content_input.decode('utf-8')
            except:
                content_str = content_input.decode('gbk', errors='ignore')
        else:
            content_str = content_input
            
        lines = content_str.splitlines()
        header_idx = -1
        for i, line in enumerate(lines[:1000]):
            l_low = line.lower()
            if 'abs time' in l_low and 'b1' in l_low and ('pt' in l_low or 'id' in l_low):
                header_idx = i
                break
        
        if header_idx == -1:
            return None
            
        df = pd.read_csv(
            io.StringIO(content_str), 
            skiprows=header_idx, 
            sep=',', 
            on_bad_lines='skip',
            low_memory=False
        )
        
        df.columns = [str(c).strip() for c in df.columns]
        cols = df.columns.tolist()
        
        try:
            time_col = next(c for c in cols if 'abs time' in c.lower())
            id_col = next((c for c in cols if c.lower() == 'id' or c.lower() == 'pt'), cols[9])
            net_col = next((c for c in cols if 'network' in c.lower()), cols[7])
            b1_idx = -1
            for i, col in enumerate(cols):
                if col.lower() == 'b1':
                    b1_idx = i
                    break
            if b1_idx == -1: b1_idx = 12
        except:
            return None

        messages = []

        def to_int_16(val):
            if pd.isna(val): return None
            s = str(val).strip().lower().replace('0x', '').replace('h', '')
            if s.endswith('.0'): s = s[:-2]
            if not s or s in ['nan', 'none']: return None
            try: return int(s, 16)
            except: return None

        for _, row in df.iterrows():
            try:
                can_id_int = to_int_16(row[id_col])
                if can_id_int is None: continue
                
                data = []
                for i in range(b1_idx, b1_idx + 8):
                    if i >= len(row): break
                    val = to_int_16(row.iloc[i])
                    if val is None: break
                    data.append(val)
                
                if not data: continue
                ts_str = str(row[time_col]).strip().replace(',', '')
                timestamp = float(ts_str)
                
                messages.append({
                    'timestamp': timestamp,
                    'timestamp_str': ts_str,
                    'channel': str(row[net_col]),
                    'can_id_int': can_id_int,
                    'can_id': format_can_id(can_id_int),
                    'direction': 'Rx',
                    'dlc': len(data),
                    'data': data
                })
            except:
                continue
                
        return messages if messages else None
    except Exception as e:
        print(f"Vehicle Spy 适配解析异常: {str(e)}")
        return None

def parse_txt_fallback(text_data):
    messages = []
    for line in text_data.splitlines():
        parts = line.strip().split()
        if len(parts) < 5: continue
        try:
            ts = float(parts[0])
            raw_id = parts[2].lower().replace('0x', '').replace('h', '')
            can_id_int = int(raw_id, 16)
            dlc = int(parts[3])
            data = [int(x, 16) for x in parts[4:4+dlc]]
            
            if data:
                messages.append({
                    'timestamp': ts, 'timestamp_str': parts[0],
                    'channel': f"CAN{parts[1]}", 'can_id_int': can_id_int,
                    'can_id': format_can_id(can_id_int),
                    'direction': 'Rx', 'dlc': dlc, 'data': data
                })
        except: continue
    return messages

def load_file(uploaded_file):
    name = uploaded_file.name.lower()
    content = uploaded_file.read()
    if name.endswith('.blf'):
        return parse_blf(content)
    try:
        text_data = content.decode('utf-8')
    except:
        text_data = content.decode('gbk', errors='ignore')
    if name.endswith('.csv'):
        return parse_csv_generic(text_data)
    res = parse_vector_asc(text_data)
    if not res:
        res = parse_txt_fallback(text_data)
    if not res:
        res = parse_custom_log(text_data)
    return res

# ==================== UDS 应答分析逻辑 ====================

def analyze_uds_negative_response(msg):
    data = msg['data']
    if len(data) >= 3:
        if (data[0] & 0xF0) == 0x00 and data[1] == 0x7F: return data[2], data[3]
        if data[0] == 0x00 and len(data) >= 5 and data[2] == 0x7F: return data[3], data[4]
    return None

def is_diagnostic_pair(req_id, resp_id):
    req_id = str(req_id).strip().upper().replace("0X", "").replace("X", "").zfill(8)
    resp_id = str(resp_id).strip().upper().replace("0X", "").replace("X", "").zfill(8)
    if req_id.startswith("18DA") or req_id.startswith("1C"):
        return req_id[4:6] == resp_id[6:8] and req_id[6:8] == resp_id[4:6]
    try:
        return abs(int(resp_id, 16) - int(req_id, 16)) == 8
    except: return False

def find_req_index(messages, resp_idx, service_code, captured_indices=None):
    """
    【升级两阶段回溯逻辑】：
    - 第一阶段：寻找服务ID、物理连接都匹配的最远且未被占用的Request。
    - 第二阶段（冗余容错）：若未匹配到相同服务的Request（可能存在ECU返回了越界服务挂起如31下返回36的挂起），
      则拉取同逻辑診断对（ID匹配）下最近的一个有效且未被占用的物理请求，建立强关联。
    """
    if captured_indices is None:
        captured_indices = set()
        
    resp_msg = messages[resp_idx]
    
    # 【第一偏好阶段】：同服务配对
    for i in range(resp_idx - 1, max(-1, resp_idx - 15000), -1):
        req = messages[i]
        if resp_msg['timestamp'] - req['timestamp'] > 8.0: 
            break
        req_data = req['data']
        if not req_data or len(req_data) < 2: 
            continue
        pci = req_data[0] & 0xF0
        req_srv = req_data[1] if pci == 0x00 else (req_data[2] if pci == 0x10 else None)
        
        if req_srv == service_code and is_diagnostic_pair(req['can_id'], resp_msg['can_id']):
            if i in captured_indices:
                break
            return i
            
    # 【第二阶段：冗余关联阶段】：当ECU报错或混淆会话时，拉取同诊断对通道内最近的一个物理诊断起点
    for i in range(resp_idx - 1, max(-1, resp_idx - 5000), -1):
        req = messages[i]
        if resp_msg['timestamp'] - req['timestamp'] > 8.0: 
            break
        req_data = req['data']
        if not req_data or len(req_data) < 2: 
            continue
        pci = req_data[0] & 0xF0
        req_srv = req_data[1] if pci == 0x00 else (req_data[2] if pci == 0x10 else None)
        
        if req_srv is not None and is_diagnostic_pair(req['can_id'], resp_msg['can_id']):
            if i in captured_indices:
                break
            return i
            
    return None
    
# ==================== UDS 服务与 NRC 常量定义 ====================
UDS_SERVICES = {
    0x10: "DiagnosticSessionControl (诊断会话控制)",
    0x11: "ECUReset (ECU复位)",
    0x14: "ClearDiagnosticInformation (清除诊断信息)",
    0x19: "ReadDTCInformation (读取DTC信息)",
    0x22: "ReadDataByIdentifier (通过ID读数据)",
    0x27: "SecurityAccess (安全访问)",
    0x2E: "WriteDataByIdentifier (通过ID写数据)",
    0x31: "RoutineControl (例程控制)",
    0x3E: "TesterPresent (待机握手)",
    0x85: "ControlDTCSetting (控制DTC设置)",
}

UDS_NRCS = {
    0x10: "GeneralReject (通用拒绝)",
    0x11: "ServiceNotSupported (不支持的服务)",
    0x12: "SubFunctionNotSupported (不支持的子功能)",
    0x13: "IncorrectMessageLengthOrInvalidFormat (不正确的消息长度或格式)",
    0x21: "BusyRepeatRequest (忙碌，重复请求)",
    0x22: "ConditionsNotCorrect (条件不满足)",
    0x24: "RequestSequenceError (请求顺序错误)",
    0x31: "RequestOutOfRange (请求超出范围)",
    0x33: "SecurityAccessDenied (安全访问拒绝/未解锁)",
    0x35: "InvalidKey (密钥无效)",
    0x36: "ExceedNumberOfAttempts (超出尝试次数)",
    0x37: "RequiredTimeDelayNotExpired (所需时延未到)",
    0x78: "RequestCorrectlyReceived-ResponsePending (正确接收，等待响应)",
    0x7E: "SubFunctionNotSupportedInActiveSession (当前会话不支持该子功能)",
    0x7F: "ServiceNotSupportedInActiveSession (当前会话不支持该服务)",
}

def get_nrc_summary(messages):
    if not messages:
        return []
    nrc_counts = {}
    for msg in messages:
        data = msg.get('data', [])
        if not data: continue
        nrc_info = None
        if len(data) >= 4 and data[1] == 0x7F:
            if (data[0] & 0xF0) == 0x00:
                nrc_info = (data[2], data[3])
        elif len(data) >= 3 and data[0] == 0x7F:
            nrc_info = (data[1], data[2])
            
        if nrc_info:
            sid, nrc = nrc_info
            if nrc == 0x78: continue
            key = (sid, nrc)
            nrc_counts[key] = nrc_counts.get(key, 0) + 1
            
    summary_data = []
    for (sid, nrc), count in nrc_counts.items():
        service_name = UDS_SERVICES.get(sid, "Unknown Service (未知服务)")
        nrc_name = UDS_NRCS.get(nrc, "Unknown NRC (未知故障码)")
        summary_data.append({
            "服务": f"0x{sid:02X} - {service_name}",
            "NRC": f"【0x{nrc:02X}】: {nrc_name}",
            "次数": count
        })
        
    summary_data = sorted(summary_data, key=lambda x: x["次数"], reverse=True)
    return summary_data    

def f_pci_data_check(data):
    return data

# ==================== 数据处理总入口 ====================
def process_log_data(uploaded_file, filter_ids_input, enable_filtering, enable_dedup):
    raw_messages = load_file(uploaded_file)
    if not raw_messages: 
        return None

    target_ids = [clean_and_parse_id(x) & 0x1FFFFFFF for x in re.split(r'[,\s\n;，；]+', filter_ids_input) if clean_and_parse_id(x)]
    
    # 优先在顶部对数据进行过滤和排重
    processed = []
    seen = set()
    for msg in raw_messages:
        clean_id = msg['can_id_int'] & 0x1FFFFFFF
        if enable_filtering and target_ids and (clean_id not in target_ids): 
            continue
        if enable_dedup and not is_tester_present(msg):
            # 去重时保留 4 位时间戳防微秒级重复
            key = (clean_id, f"{msg['timestamp']:.4f}", "".join([f"{x:02X}" for x in msg['data']]))
            if key in seen: 
                continue
            seen.add(key)
        processed.append(msg)

    # 初始化明细与报表结构
    uds_web_details = []
    diag_report_txt = io.StringIO()
    report_time = pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S")
    
    diag_report_txt.write("="*120 + "\n")
    diag_report_txt.write(f"UDS 诊断否定应答 (Negative Response) 深度分析报告\n")
    diag_report_txt.write(f"生成时间: {report_time}\n")
    diag_report_txt.write("="*120 + "\n\n")
    
    header_line = f"{'时间戳':<22} {'通道':<12} {'CAN ID':<15} {'DLC':<8} {'数据 (Hex)':<30}\n"
    diag_report_txt.write(header_line)
    diag_report_txt.write("-" * 120 + "\n")

    neg_count = 0
    summary_map = {}
    
    captured_indices = set()

    for idx, msg in enumerate(processed):
        if idx in captured_indices:
            continue
            
        res = analyze_uds_negative_response(msg)
        if res:
            service_code, nrc_code = res
            req_idx = find_req_index(processed, idx, service_code, captured_indices)
            
            srv_info = UDS_SERVICES.get(service_code, f"Unknown(0x{service_code:02X})")
            nrc_info = UDS_NRC.get(nrc_code, f"Unknown(0x{nrc_code:02X})")
            
            start_scan = req_idx if req_idx is not None else idx
            end_scan = idx
            
            if nrc_code == 0x78:
                target_resp_id = msg['can_id']
                # 向后扫描最多 500 条报文或 5.0 秒，寻找最终响应
                for f_idx in range(idx + 1, min(len(processed), idx + 500)):
                    f_msg = processed[f_idx]
                    if f_msg['timestamp'] - msg['timestamp'] > 5.0:
                        break
                    
                    if f_msg['can_id'] == target_resp_id:
                        f_data = f_msg['data']
                        if f_data and len(f_data) >= 2:
                            pci = f_data[0] & 0xF0
                            
                            # 【核心修复】：提取后续 Pending 中的服务代码，只在属于同类服务挂起时合并
                            is_another_pending = False
                            f_pending_srv = None
                            if pci == 0x00 and f_data[1] == 0x7F and len(f_data) >= 4 and f_data[3] == 0x78:
                                f_pending_srv = f_data[2]
                            elif pci == 0x10 and len(f_data) >= 5 and f_data[2] == 0x7F and f_data[4] == 0x78:
                                f_pending_srv = f_data[3]
                                
                            if f_pending_srv == service_code:
                                is_another_pending = True
                            
                            if is_another_pending:
                                end_scan = f_idx
                                continue
                            
                            is_final_resp = False
                            # 标准的正/负最终响应校验
                            if pci == 0x00 and f_data[1] == (service_code + 0x40):
                                is_final_resp = True
                            elif pci == 0x10 and len(f_data) >= 3 and f_data[2] == (service_code + 0x40):
                                is_final_resp = True
                            elif pci == 0x00 and f_data[1] == 0x7F and len(f_data) >= 4 and f_data[2] == service_code and f_data[3] != 0x78:
                                is_final_resp = True
                            elif pci == 0x10 and len(f_data) >= 5 and f_data[2] == 0x7F and f_data[3] == service_code and f_data[4] != 0x78:
                                is_final_resp = True
                            
                            # 【双重备用校验】：如果关联请求服务 ID (req_srv) 与 service_code 不符，
                            # 当遇到实际请求服务的正负响应时也可以使事件闭环：
                            if not is_final_resp and req_idx is not None:
                                r_msg = processed[req_idx]
                                r_data = r_msg['data']
                                if len(r_data) >= 2:
                                    r_pci = r_data[0] & 0xF0
                                    r_srv = r_data[1] if r_pci == 0x00 else (r_data[2] if r_pci == 0x10 else None)
                                    if r_srv is not None and r_srv != service_code:
                                        if pci == 0x00 and f_data[1] == (r_srv + 0x40):
                                            is_final_resp = True
                                        elif pci == 0x10 and len(f_data) >= 3 and f_data[2] == (r_srv + 0x40):
                                            is_final_resp = True
                                        elif pci == 0x00 and f_data[1] == 0x7F and len(f_data) >= 4 and f_data[2] == r_srv and f_data[3] != 0x78:
                                            is_final_resp = True
                                        elif pci == 0x10 and len(f_data) >= 5 and f_data[2] == 0x7F and f_data[3] == r_srv and f_data[4] != 0x78:
                                            is_final_resp = True

                            if is_final_resp:
                                end_scan = f_idx
                                if pci == 0x10:
                                    for c_idx in range(f_idx + 1, min(len(processed), f_idx + 40)):
                                        c_msg = processed[c_idx]
                                        c_data = c_msg['data']
                                        if c_data and len(c_data) > 0:
                                            c_pci = c_data[0] & 0xF0
                                            if c_msg['can_id'] in [target_resp_id, processed[start_scan]['can_id']] and c_pci in [0x20, 0x30]:
                                                end_scan = c_idx
                                            else:
                                                break
                                break

            # 统计并打标记
            summary_map[(srv_info, nrc_info)] = summary_map.get((srv_info, nrc_info), 0) + 1
            neg_count += 1
            
            # 记录已被处理的区间，防止重复扫描
            for captured_i in range(start_scan, end_scan + 1):
                captured_indices.add(captured_i)
            
            # --- 写入事件分割标题 ---
            event_header = f"\n>>> 诊断异常事件 #{neg_count} (服务: 0x{service_code:02X} - {srv_info}) | 触发源NRC: 【0x{nrc_code:02X}】 : {nrc_info}\n"
            diag_report_txt.write(event_header)
            diag_report_txt.write("-" * 120 + "\n")
            
            allowed_ids = {msg['can_id'].upper().strip()}
            if req_idx is not None:
                allowed_ids.add(processed[req_idx]['can_id'].upper().strip())
            allowed_ids.update({"7DF", "18DBF1FD"})

            # 写入该闭环中包含的所有相关物理报文
            for i in range(start_scan, end_scan + 1):
                loop_msg = processed[i]
                msg_id_upper = loop_msg['can_id'].upper().strip()
                if msg_id_upper in allowed_ids:
                    diag_report_txt.write(format_msg_line(loop_msg) + "\n")
            
            diag_report_txt.write("-" * 120 + "\n")
            
            # 构建网页明细表格格式数据
            if req_idx is not None:
                r = processed[req_idx]
                uds_web_details.append({
                    "事件编号": f"#{neg_count}", "报文类型": "📤 请求", 
                    "时间戳": r.get('timestamp_str') or f"{r['timestamp']:.6f}", 
                    "CAN ID": r['can_id'], "数据 (Hex)": " ".join([f"{x:02X}" for x in r['data']]), 
                    "服务映射": srv_info, "诊断结果/NRC原因": ""
                })
            
            uds_web_details.append({
                "事件编号": f"#{neg_count}", "报文类型": "❌ 否定应答", 
                "时间戳": msg.get('timestamp_str') or f"{msg['timestamp']:.6f}", 
                "CAN ID": msg['can_id'], "数据 (Hex)": " ".join([f"{x:02X}" for x in msg['data']]), 
                "服务映射": srv_info, "诊断结果/NRC原因": nrc_info
            })
            
            if end_scan > idx:
                f_msg = processed[end_scan]
                f_data = f_msg['data']
                f_pci = f_data[0] & 0xF0 if f_data else 0
                
                is_pos = (f_pci == 0x00 and len(f_data) >= 2 and f_data[1] == (service_code + 0x40)) or \
                         (f_pci == 0x10 and len(f_data) >= 3 and f_data[2] == (service_code + 0x40))
                
                # 双重校验如果是关联服务请求响应的闭合
                if not is_pos and req_idx is not None:
                    r_msg = processed[req_idx]
                    r_data = r_msg['data']
                    if len(r_data) >= 2:
                        r_pci = r_data[0] & 0xF0
                        r_srv = r_data[1] if r_pci == 0x00 else (r_data[2] if r_pci == 0x10 else None)
                        if r_srv is not None:
                            is_pos = (f_pci == 0x00 and len(f_data) >= 2 and f_data[1] == (r_srv + 0x40)) or \
                                     (f_pci == 0x10 and len(f_data) >= 3 and f_data[2] == (r_srv + 0x40))

                if is_pos:
                    uds_web_details.append({
                        "事件编号": f"#{neg_count}", "报文类型": "✅ 最终正响应", 
                        "时间戳": f_msg.get('timestamp_str') or f"{f_msg['timestamp']:.6f}", 
                        "CAN ID": f_msg['can_id'], "数据 (Hex)": " ".join([f"{x:02X}" for x in f_pci_data_check(f_data)]), 
                        "服务映射": srv_info, "诊断结果/NRC原因": "Success"
                    })
                else:
                    _, final_nrc = analyze_uds_negative_response(f_msg) or (None, None)
                    fin_nrc_desc = UDS_NRC.get(final_nrc, f"Unknown(0x{final_nrc:02X})") if final_nrc else "Final Negative"
                    uds_web_details.append({
                        "事件编号": f"#{neg_count}", "报文类型": "❌ 最终否定应答", 
                        "时间戳": f_msg.get('timestamp_str') or f"{f_msg['timestamp']:.6f}", 
                        "CAN ID": f_msg['can_id'], "数据 (Hex)": " ".join([f"{x:02X}" for x in f_msg['data']]), 
                        "服务映射": srv_info, "诊断结果/NRC原因": fin_nrc_desc
                    })

    # 输出纯文本 log_txt 报文流文件
    log_txt = io.StringIO()
    for msg in processed: 
        log_txt.write(format_msg_line(msg) + "\n")

    return {
        'raw_count': len(raw_messages), 
        'filtered_count': len(processed), 
        'neg_count': neg_count,
        'log_txt_bytes': log_txt.getvalue().encode('utf-8'),
        'diag_txt_bytes': diag_report_txt.getvalue().encode('utf-8'),
        'df_details': pd.DataFrame(uds_web_details),
        'df_summary': pd.DataFrame([{"服务": k[0], "NRC": k[1], "次数": v} for k, v in summary_map.items()]),
        'df_preview': pd.DataFrame([{ "时间戳": m.get('timestamp_str') or f"{m['timestamp']:.6f}", "ID": m['can_id'], "数据": " ".join([f"{x:02X}" for x in m['data']]) } for m in processed[:100]]),
        'df_all_uds': pd.DataFrame([{ "时间戳": m.get('timestamp_str') or f"{m['timestamp']:.6f}", "ID": m['can_id'], "数据": " ".join([f"{x:02X}" for x in m['data']]) } for m in processed])
    }