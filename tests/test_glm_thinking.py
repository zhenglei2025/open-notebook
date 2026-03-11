"""
GLM Thinking Mode Test Script
==============================
Tests different methods to disable thinking/reasoning mode for GLM models.
Sends requests using the OpenAI-compatible API and inspects the response
to determine whether thinking was actually disabled.

Usage:
    python tests/test_glm_thinking.py

Configure the variables below before running.
"""

import json
import requests
import time

# ============================================================
# Configuration – edit these before running
# ============================================================
API_BASE_URL = "https://api.gpt.ge/v1"                   # GLM API base URL
MODEL_NAME = "glm-4.7"                                   # Model to test
API_KEY = "sk-"  # Your API key
# ============================================================

SIMPLE_PROMPT = "1+1等于几？只回答数字。"

HEADERS = {
    "Content-Type": "application/json",
    "Authorization": f"Bearer {API_KEY}",
}

CHAT_ENDPOINT = f"{API_BASE_URL}/chat/completions"


def _send_request(label: str, body: dict) -> dict | None:
    """Send a request and return the parsed JSON response."""
    print(f"\n{'='*70}")
    print(f"TEST: {label}")
    print(f"{'='*70}")
    print(f"Endpoint : {CHAT_ENDPOINT}")
    print(f"Model    : {body.get('model', MODEL_NAME)}")
    print(f"Request body (extra fields only):")
    display = {k: v for k, v in body.items() if k not in ("model", "messages")}
    print(json.dumps(display, indent=2, ensure_ascii=False))
    print("-" * 70)

    try:
        start = time.time()
        resp = requests.post(CHAT_ENDPOINT, headers=HEADERS, json=body, timeout=60)
        elapsed = time.time() - start
        print(f"Status   : {resp.status_code}  ({elapsed:.2f}s)")

        if resp.status_code != 200:
            print(f"Error    : {resp.text[:500]}")
            return None

        data = resp.json()
        # Extract content
        choice = data.get("choices", [{}])[0]
        message = choice.get("message", {})
        content = message.get("content", "")
        reasoning = message.get("reasoning_content") or message.get("reasoning") or None

        # Token usage
        usage = data.get("usage", {})
        prompt_tokens = usage.get("prompt_tokens", "?")
        completion_tokens = usage.get("completion_tokens", "?")
        total_tokens = usage.get("total_tokens", "?")

        print(f"Content  : {content[:200]}")
        if reasoning:
            print(f"Reasoning: {str(reasoning)[:200]}")
        else:
            print(f"Reasoning: (none)")
        print(f"Tokens   : prompt={prompt_tokens}, completion={completion_tokens}, total={total_tokens}")

        # Check for thinking indicators
        has_think_tag = "<think>" in content or "</think>" in content
        has_reasoning = reasoning is not None and len(str(reasoning)) > 0

        if has_think_tag or has_reasoning:
            print(f"RESULT   : ❌ Thinking is ENABLED (think_tag={has_think_tag}, reasoning_field={has_reasoning})")
        else:
            print(f"RESULT   : ✅ Thinking appears DISABLED")

        return data
    except requests.exceptions.Timeout:
        print("Error    : Request timed out")
        return None
    except Exception as e:
        print(f"Error    : {e}")
        return None


def test_baseline():
    """Test 1: Baseline request without any thinking control."""
    body = {
        "model": MODEL_NAME,
        "messages": [{"role": "user", "content": SIMPLE_PROMPT}],
    }
    return _send_request("Baseline (no thinking control)", body)


def test_extra_body_thinking_disabled():
    """Test 2: Use extra_body with thinking.type = disabled."""
    body = {
        "model": MODEL_NAME,
        "messages": [{"role": "user", "content": SIMPLE_PROMPT}],
        "thinking": {"type": "disabled"},
    }
    return _send_request('Top-level "thinking": {"type": "disabled"}', body)


def test_extra_body_enable_thinking_false():
    """Test 3: Use extra_body with enable_thinking = False."""
    body = {
        "model": MODEL_NAME,
        "messages": [{"role": "user", "content": SIMPLE_PROMPT}],
        "enable_thinking": False,
    }
    return _send_request('Top-level "enable_thinking": false', body)


def test_both_params():
    """Test 4: Use both thinking.type=disabled AND enable_thinking=False."""
    body = {
        "model": MODEL_NAME,
        "messages": [{"role": "user", "content": SIMPLE_PROMPT}],
        "thinking": {"type": "disabled"},
        "enable_thinking": False,
    }
    return _send_request('Both "thinking": {"type": "disabled"} + "enable_thinking": false', body)


def test_do_sample_false():
    """Test 5: Set do_sample=False which some GLM versions use to disable thinking."""
    body = {
        "model": MODEL_NAME,
        "messages": [{"role": "user", "content": SIMPLE_PROMPT}],
        "do_sample": False,
    }
    return _send_request('"do_sample": false', body)


def test_temperature_zero():
    """Test 6: Set temperature=0.01 to minimize reasoning."""
    body = {
        "model": MODEL_NAME,
        "messages": [{"role": "user", "content": SIMPLE_PROMPT}],
        "temperature": 0.01,
    }
    return _send_request('"temperature": 0.01 (near zero)', body)


def test_thinking_disabled_plus_temp():
    """Test 7: Combine thinking disabled + low temperature."""
    body = {
        "model": MODEL_NAME,
        "messages": [{"role": "user", "content": SIMPLE_PROMPT}],
        "thinking": {"type": "disabled"},
        "enable_thinking": False,
        "temperature": 0.01,
    }
    return _send_request('Combined: thinking disabled + enable_thinking=false + temp=0.01', body)


def test_chat_template_kwargs():
    """Test 8: Use chat_template_kwargs to disable thinking (vLLM/SGLang style)."""
    body = {
        "model": MODEL_NAME,
        "messages": [{"role": "user", "content": SIMPLE_PROMPT}],
        "chat_template_kwargs": {"enable_thinking": False},
    }
    return _send_request('"chat_template_kwargs": {"enable_thinking": false}', body)


def main():
    print("=" * 70)
    print("GLM Thinking Mode Test")
    print(f"API URL  : {API_BASE_URL}")
    print(f"Model    : {MODEL_NAME}")
    print(f"API Key  : {API_KEY[:8]}...{API_KEY[-4:]}" if len(API_KEY) > 12 else f"API Key  : (not set)")
    print("=" * 70)

    if API_KEY == "YOUR_API_KEY_HERE":
        print("\n⚠️  Please set API_KEY in the script before running!\n")
        return

    tests = [
        test_baseline,
        test_extra_body_thinking_disabled,
        test_extra_body_enable_thinking_false,
        test_both_params,
        test_do_sample_false,
        test_temperature_zero,
        test_thinking_disabled_plus_temp,
        test_chat_template_kwargs,
    ]

    results = []
    for test_fn in tests:
        data = test_fn()
        results.append((test_fn.__doc__ or test_fn.__name__, data))
        time.sleep(0.5)  # Rate limiting

    # Summary
    print("\n")
    print("=" * 70)
    print("SUMMARY")
    print("=" * 70)
    for label, data in results:
        label_clean = label.strip().split(":")[0] if ":" in label else label.strip()
        if data is None:
            status = "⚠️  Request failed"
        else:
            choice = data.get("choices", [{}])[0]
            message = choice.get("message", {})
            content = message.get("content", "")
            reasoning = message.get("reasoning_content") or message.get("reasoning")
            has_think = "<think>" in content or "</think>" in content
            has_reasoning = reasoning is not None and len(str(reasoning)) > 0
            if has_think or has_reasoning:
                status = "❌ Thinking ENABLED"
            else:
                status = "✅ Thinking DISABLED"
            usage = data.get("usage", {})
            tokens = usage.get("total_tokens", "?")
            status += f"  (tokens: {tokens})"
        print(f"  {label_clean:<20s}  {status}")


if __name__ == "__main__":
    main()
