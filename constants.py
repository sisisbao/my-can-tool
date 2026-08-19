# constants.py

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

# NRC 诊断否定响应映射字典
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

def format_can_id(arbitration_id):
    """根据CAN ID长度自动调整显示为3位或8位十六进制字符串"""
    if arbitration_id > 0x7FF:
        return f"{arbitration_id:08X}"
    else:
        return f"{arbitration_id:03X}"