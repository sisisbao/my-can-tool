# ai_engine.py
import google.generativeai as genai
from openai import OpenAI

class AIManager:
    @staticmethod
    def call_deepseek(api_key, model, prompt, history):
        """API 与 OpenAI 接口完美兼容的 DeepSeek 调用实现"""
        client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com")
        messages = [{"role": "system", "content": "你是一位车载总线诊断与 UDS 先锋级专家，精通 ISO-14229 及各类总线解析。"}]
        for h in history:
            messages.append({"role": h["role"], "content": h["content"]})
        messages.append({"role": "user", "content": prompt})
        
        response = client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=0.3
        )
        return response.choices[0].message.content

    @staticmethod
    def call_kimi(api_key, model, prompt, history):
        """API 与 OpenAI 接口兼容的 Kimi(Moonshot) 调用实现"""
        client = OpenAI(api_key=api_key, base_url="https://api.moonshot.cn/v1")
        messages = [{"role": "system", "content": "你是一个严密的汽车 ECU 诊断总线分析机器人。"}]
        for h in history:
            messages.append({"role": h["role"], "content": h["content"]})
        messages.append({"role": "user", "content": prompt})

        response = client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=0.3
        )
        return response.choices[0].message.content

    @staticmethod
    def call_gemini(api_key, model, prompt):
        """Google Gemini 引擎适配器"""
        genai.configure(api_key=api_key)
        m = genai.GenerativeModel(model)
        response = m.generate_content(prompt)
        return response.text