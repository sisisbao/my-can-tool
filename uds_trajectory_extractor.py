import pandas as pd
import re

# 常用 UDS 请求服务字典映射
UDS_SERVICES = {
    0x10: "诊断会话控制(SessionControl)",
    0x11: "ECU复位(ECUReset)",
    0x22: "读取DID数据(ReadData)",
    0x27: "安全访问(SecurityAccess)",
    0x28: "通信控制(CommunicationControl)",
    0x2E: "写入DID数据(WriteData)",
    0x14: "清除诊断信息(ClearDTC)",
    0x19: "读取DTC信息(ReadDTC)",
    0x31: "例程控制(RoutineControl)",
    0x34: "请求下载(RequestDownload)",
    0x35: "请求上传(RequestUpload)",
    0x36: "数据传输(TransferData)",
    0x37: "请求退出传输(RequestTransferExit)",
    0x85: "控制DTC设置(ControlDTCSetting)",
}

# UDS NRC 否定响应状态字典映射
UDS_NRCS = {
    0x10: "常规拒绝(GeneralReject)",
    0x11: "不支持该服务(ServiceNotSupported)",
    0x12: "不支持该子功能(SubFunctionNotSupported)",
    0x13: "报文长度不符或格式错误(IncorrectMessageLengthOrInvalidFormat)",
    0x21: "忙碌重复请求(BusyRepeatRequest)",
    0x22: "条件不满足(ConditionsNotCorrect)",
    0x24: "请求序列错误(RequestSequenceError)",
    0x31: "参数超出范围(RequestOutOfRange)",
    0x33: "安全访问拒绝(SecurityAccessDenied)",
    0x35: "密钥无效(InvalidKey)",
    0x36: "超出尝试次数(ExceedNumberOfAttempts)",
    0x37: "延时未到(RequiredTimeDelayNotExpired)",
    0x78: "等待响应(ResponsePending)",
    0x7E: "当前会话不支持该子功能(SubFunctionNotSupportedInActiveSession)",
    0x7F: "当前会话不支持该服务(ServiceNotSupportedInActiveSession)",
}

class UDSTrajectoryExtractor:
    
    @staticmethod
    def clean_hex_data(data_val):
        """清洗数据字段，提取出 Hex 字节列表"""
        if pd.isna(data_val):
            return []
        val_str = str(data_val).strip()
        hex_list = re.findall(r'[0-9a-fA-F]{2}', val_str)
        return hex_list

    @staticmethod
    def process_dataframe(df):
        """
        静态处理 DataFrame
        1. 解析所有服务，保留请求(TX)与响应(RX)
        2. 过滤 3E 握手及所有服务带 78 的等待响应 (Response Pending) 
        3. 进行多帧协议重组 (ISO-TP)
        4. 强力折叠合并 36 -> 76 传输链路
        """
        # 1. 自动定位关键列名
        col_mapping = {}
        for col in df.columns:
            col_upper = str(col).upper()
            if "TIME" in col_upper or "时间" in col_upper:
                col_mapping['time'] = col
            elif "ID" in col_upper:
                col_mapping['id'] = col
            elif "DATA" in col_upper or "数据" in col_upper:
                col_mapping['data'] = col
            elif "DIR" in col_upper or "方向" in col_upper:
                col_mapping['dir'] = col

        time_col = col_mapping.get('time')
        id_col = col_mapping.get('id')
        data_col = col_mapping.get('data')
        dir_col = col_mapping.get('dir')

        if not data_col:
            return []

        # 2. 初始化重组 Buffer 字典（隔离方向与通道）
        buffers = {}
        extracted_items = []

        for index, row in df.iterrows():
            # 获取报文 ID 与方向
            can_id = str(row[id_col]).strip().upper() if id_col else f"TEMP_ID"
            
            direction_str = "TX"
            if dir_col:
                dir_val = str(row[dir_col]).strip().upper()
                if "RX" in dir_val or "接收" in dir_val:
                    direction_str = "RX"

            # 提取原始数据字节，并转换为整数列表（静态方法调用修改）
            hex_bytes = UDSTrajectoryExtractor.clean_hex_data(row[data_col])
            if not hex_bytes:
                continue

            try:
                data = [int(b, 16) for b in hex_bytes]
            except ValueError:
                continue

            if not data:
                continue

            # 使用 ID 和方向确定唯一的 Buffer 隔离标识
            buffer_key = f"{can_id}_{direction_str}"

            # --- ISO-TP 多帧重组逻辑 ---
            pci = data[0] & 0xF0
            assembled_payload = None
            assembled_timestamp = None

            # [Case A] 单帧 (Single Frame)
            if pci == 0x00:
                length = data[0] & 0x0F
                if length == 0 and len(data) > 1:  # CAN FD 长单帧
                    length = data[1]
                    assembled_payload = data[2 : 2 + length]
                elif 0 < length < len(data):
                    assembled_payload = data[1 : 1 + length]
                assembled_timestamp = row[time_col] if time_col else index

            # [Case B] 首帧 (First Frame)
            elif pci == 0x10 and len(data) >= 2:
                length = ((data[0] & 0x0F) << 8) | data[1]
                start_byte_idx = 2
                if length == 0 and len(data) >= 6:  # CAN FD 首帧溢出
                    length = (data[2] << 24) | (data[3] << 16) | (data[4] << 8) | data[5]
                    start_byte_idx = 6
                
                t_val = row[time_col] if time_col else index
                buffers[buffer_key] = {
                    'total_len': length,
                    'data': data[start_byte_idx:],
                    'timestamp': t_val
                }
                
                buf = buffers[buffer_key]
                if len(buf['data']) >= buf['total_len']:
                    assembled_payload = buf['data'][:buf['total_len']]
                    assembled_timestamp = buf['timestamp']
                    del buffers[buffer_key]

            # [Case C] 连续帧 (Consecutive Frame)
            elif pci == 0x20:
                if buffer_key in buffers:
                    buf = buffers[buffer_key]
                    buf['data'].extend(data[1:])
                    
                    if len(buf['data']) >= buf['total_len']:
                        assembled_payload = buf['data'][:buf['total_len']]
                        assembled_timestamp = buf['timestamp']
                        del buffers[buffer_key]

            # 3. 解析并过滤数据
            if assembled_payload:
                service_code = assembled_payload[0]
                
                # ==== 核心过滤 1：丢弃 3E (握手) / 7E (握手响应) ====
                if service_code in [0x3E, 0x7E]:
                    continue
                if service_code == 0x7F and len(assembled_payload) >= 2 and assembled_payload[1] == 0x3E:
                    continue

                # ==== 核心过滤 2：彻底丢弃所有的 0x78 (Response Pending) 挂起响应数据 ====
                if service_code == 0x7F and len(assembled_payload) >= 3 and assembled_payload[2] == 0x78:
                    continue

                raw_hex_str = " ".join([f"{b:02X}" for b in assembled_payload])
                
                # 格式化时间戳
                if isinstance(assembled_timestamp, (int, float)):
                    ts_str = f"{assembled_timestamp:.3f}"
                else:
                    ts_str = str(assembled_timestamp)

                # 解析服务的可读信息
                service_desc = "Unknown"
                if service_code == 0x7F:
                    # 否定响应 (7F [服务ID] [NRC码])
                    orig_sid = assembled_payload[1] if len(assembled_payload) > 1 else 0
                    nrc_code = assembled_payload[2] if len(assembled_payload) > 2 else 0
                    orig_name = UDS_SERVICES.get(orig_sid, f"0x{orig_sid:02X}")
                    nrc_name = UDS_NRCS.get(nrc_code, f"0x{nrc_code:02X}")
                    service_desc = f"否定响应 ({orig_name} -> ❌ {nrc_name})"
                elif service_code >= 0x40 and (service_code - 0x40) in UDS_SERVICES:
                    # 正响应 (请求ID + 0x40)
                    orig_sid = service_code - 0x40
                    service_desc = f"{UDS_SERVICES.get(orig_sid)} 正响应"
                else:
                    # 普通请求
                    service_desc = UDS_SERVICES.get(service_code, f"未知服务 0x{service_code:02X}")

                extracted_items.append({
                    'sid_hex': f"{service_code:02X}",
                    'service_desc': service_desc,
                    'timestamp': ts_str,
                    'dir': direction_str,
                    'raw_data': raw_hex_str,
                    'count': 1
                })

        # 4. 核心打包：折叠 36 请求与 76 响应
        final_items = []
        i = 0
        n = len(extracted_items)
        
        while i < n:
            item = extracted_items[i]
            
            # 如果碰到了 36 或 76，开启统计合并
            if item['sid_hex'] in ["36", "76"]:
                start_ts = item['timestamp']
                count_36 = 0
                count_76 = 0
                
                # 连续扫描，将紧贴着的 36/76 的数量收集起来
                while i < n and extracted_items[i]['sid_hex'] in ["36", "76"]:
                    if extracted_items[i]['sid_hex'] == "36":
                        count_36 += 1
                    elif extracted_items[i]['sid_hex'] == "76":
                        count_76 += 1
                    i += 1
                
                final_items.append({
                    'type': 'transfer_group',
                    'timestamp': start_ts,
                    'count_36': count_36,
                    'count_76': count_76,
                    'sid_hex': 'GROUP_36'
                })
            else:
                # 其他常规服务透传
                final_items.append(item)
                i += 1

        return final_items

    @staticmethod
    def get_token_friendly_markdown(df):
        """生成 Markdown 格式的提纯轨迹报告（改写为 staticmethod 避免类方法解绑报错）"""
        # 直接使用 UDSTrajectoryExtractor 调用它
        items = UDSTrajectoryExtractor.process_dataframe(df)
        lines = []
        for i, item in enumerate(items, 1):
            # 处理合并后的 36/76 传输链路展示
            if item.get('type') == 'transfer_group':
                ts = item['timestamp']
                c36 = item['count_36']
                c76 = item['count_76']
                lines.append(f"{i}. [{ts}] -> 36 (数据传输 x{c36}次) -> 76 (数据传输正响应 x{c76}次)")
            
            # 处理其他普通指令显示
            else:
                sid_hex = item.get('sid_hex', '??')
                desc = item.get('service_desc', 'Unknown')
                timestamp = item.get('timestamp', '0.000')
                direction = "->" if item.get('dir') == 'TX' else "<-"
                raw_hex = item.get('raw_data', "")
                lines.append(f"{i}. [{timestamp}] {direction} {raw_hex} ({desc})")
        
        return "\n".join(lines)