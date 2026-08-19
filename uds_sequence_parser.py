# uds_sequence_parser.py
import re
import pandas as pd

# UDS 常用服务短十六进制及其标准中文说明
UDS_SERVICES_SHORT = {
    "10": "会话控制", "11": "复位", "14": "清除DTC", "19": "读取DTC",
    "22": "读取数据", "27": "安全解锁", "28": "通信控制", "2E": "写入数据",
    "31": "例程控制", "34": "请求下载", "35": "请求上传", "36": "传输数据",
    "37": "退出传输", "3E": "握手", "85": "关闭DTC"
}

def load_sequence_file(file_obj) -> pd.DataFrame:
    """
    流式读取上传的 Excel 或 CSV 文件，统一返回 DataFrame。
    """
    if file_obj.name.endswith('.csv'):
        return pd.read_csv(file_obj)
    else:
        return pd.read_excel(file_obj)

def guess_uds_column(df: pd.DataFrame) -> int:
    """
    自动在列名中寻找可能代表“UDS指令/发送报文/TX数据”的候选列。
    返回最匹配的列索引（若无匹配则返回0作为安全备选项）。
    """
    candidate_cols = list(df.columns)
    keywords = ['tx', 'request', '发送', '请求', '指令', 'cmd', 'command', '数据', 'data', 'uds']
    for idx, col in enumerate(candidate_cols):
        # 只要列名中包含上述关键字之一，立即定位
        if any(k in str(col).lower() for k in keywords):
            return idx
    return 0

def parse_uds_sequence(df: pd.DataFrame, column_name: str) -> tuple:
    """
    修改说明：
    1. 返回值由 str 改为 tuple (preview_str, metadata_md)
    2. 使用 df.iterrows() 遍历，以便抓取同一行的 '备注'、'名称' 等辅助信息
    """
    extracted_list = []
    last_sid = None
    
    # --- 新增：用于存储发送给 AI 的详细规约字典 (Markdown 格式) ---
    metadata_lines = [
        "| 步骤 | 名称 | 主控请求(Hex定义) | ECU预期应答 | 备注(参数布局/算法) |",
        "| :--- | :--- | :--- | :--- | :--- |"
    ]

    # 改为遍历整行数据
    for idx, row in df.iterrows():
        # 获取指定列的原始值
        row_val = str(row.get(column_name, '')).strip()
        if not row_val or row_val.lower() == 'nan':
            continue
            
        # 1. 预处理：去掉 0x 和干扰符号 (保持原逻辑)
        clean_row = re.sub(r'0[xX]', '', row_val)
        
        # 2. 增强匹配 (保持原逻辑)
        raw_bytes = re.findall(r'\b[0-9a-fA-F]{2}\b', clean_row)
        
        if not raw_bytes:
            single_byte = re.findall(r'^[0-9a-fA-F]{2}$', clean_row)
            if single_byte:
                raw_bytes = single_byte

        if raw_bytes:
            sid = raw_bytes[0].upper()
            
            # --- 原有逻辑：生成预览字符串 ---
            if sid == "36":
                if last_sid != "36":
                    extracted_list.append("36 (数据传输循环)")
                    last_sid = "36"
            else:
                # 拼接指令（原有的 31 服务特殊处理逻辑保持不变）
                if sid == "31":
                    hex_cmd = " ".join(raw_bytes[:4]).upper()
                else:
                    hex_cmd = " ".join(raw_bytes[:3]).upper()
                
                # 假设 UDS_SERVICES_SHORT 已在外部定义
                comment = UDS_SERVICES_SHORT.get(sid, "")
                extracted_list.append(f"{hex_cmd}({comment})" if comment else hex_cmd)
                last_sid = sid

            # --- 【核心新增】：抓取备注等元数据送给 AI ---
            # 这里的列名 '名称', 'ECU应答', '备注' 请根据你 Excel 的实际表头微调
            step_idx = str(row.get('步骤', idx + 1))
            name = str(row.get('名称', 'N/A')).replace('\n', ' ')
            resp = str(row.get('ECU应答', 'N/A')).replace('\n', ' ')
            remark = str(row.get('备注', 'N/A')).replace('\n', ' ')
            
            # 将整行的详细信息记录到 Markdown 表格中
            metadata_lines.append(f"| {step_idx} | {name} | `{row_val}` | `{resp}` | {remark} |")
                
    preview_str = " -> ".join(extracted_list)
    metadata_md = "\n".join(metadata_lines)
    
    return preview_str, metadata_md

