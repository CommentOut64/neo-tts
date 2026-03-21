from __future__ import annotations

from typing import Any


def build_pytorch_optimized_inference(
    gpt_path: str,
    sovits_path: str,
    cnhubert_path: str,
    bert_path: str,
) -> Any:
    # 迁移期适配层：后端统一通过此入口构造 legacy 推理内核。
    from run_optimized_inference import GPTSoVITSOptimizedInference

    return GPTSoVITSOptimizedInference(
        gpt_path=gpt_path,
        sovits_path=sovits_path,
        cnhubert_base_path=cnhubert_path,
        bert_path=bert_path,
    )
