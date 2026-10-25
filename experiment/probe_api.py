"""Check one short SiliconFlow request before starting OpenEvolve."""

import os
import sys
from time import perf_counter

from openai import OpenAI
from openevolve.utils.request_budget import reserve_request

BASE_URL = os.environ.get("TN_API_BASE", "https://api.siliconflow.cn/v1")
PREFERRED = ("deepseek-ai/DeepSeek-V3.2",)
PROBE_PROMPT = (
    "Return only a Python function named choose_pair(active). It takes a list "
    "of nonempty sets and returns two different integer positions. Choose the "
    "pair whose union has the fewest elements. Break ties by position."
)


def main():
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        raise RuntimeError("OPENAI_API_KEY is missing")
    client = OpenAI(api_key=key, base_url=BASE_URL, timeout=30.0, max_retries=0)
    start = perf_counter()
    reserve_request("model_list", run_id=os.environ.get("TN_RUN_ID"))
    models = {item.id for item in client.models.list().data}
    print(f"API model list: {len(models)} models, {perf_counter() - start:.1f}s",
          file=sys.stderr, flush=True)
    candidates = [name for name in PREFERRED if name in models]
    if not candidates:
        raise RuntimeError("No preferred chat model is listed for this API key")
    errors = []
    for model in candidates:
        start = perf_counter()
        try:
            reserve_request("probe_completion", run_id=os.environ.get("TN_RUN_ID"))
            response = client.chat.completions.create(
                model=model, messages=[{"role": "user", "content": PROBE_PROMPT}],
                max_tokens=256, stream=False, timeout=50.0,
                extra_body={"enable_thinking": False},
            )
            if not response.choices or not response.choices[0].message.content:
                raise RuntimeError("empty code completion")
            print(f"API probe OK: {model}, {perf_counter() - start:.1f}s",
                  file=sys.stderr, flush=True)
            print(model, flush=True)
            return
        except Exception as exc:
            message = f"{model}: {type(exc).__name__}: {exc}"
            print(f"API probe failed: {message}", file=sys.stderr, flush=True)
            errors.append(message)
    raise RuntimeError("All preferred models failed: " + " | ".join(errors))


if __name__ == "__main__":
    main()
