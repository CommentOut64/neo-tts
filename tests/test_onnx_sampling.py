import unittest

import numpy as np

from run_onnx_inference import sample_topk


class SampleTopKTests(unittest.TestCase):
    def test_sample_topk_respects_requested_top_k(self):
        np.random.seed(0)
        topk_values = np.array([[10.0, 9.0, 8.0, 7.0]], dtype=np.float32)
        topk_indices = np.array([[100, 200, 300, 400]], dtype=np.int64)

        seen = set()
        for _ in range(50):
            sample = sample_topk(topk_values, topk_indices, temperature=1.0, top_k=2)
            seen.add(int(sample[0, 0]))

        self.assertTrue(seen <= {100, 200})


if __name__ == "__main__":
    unittest.main()
