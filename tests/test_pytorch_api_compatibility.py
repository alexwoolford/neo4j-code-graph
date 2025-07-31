"""
Test PyTorch API compatibility to catch breaking changes early.

This test file focuses on ensuring our code is compatible with PyTorch APIs
and catches issues before they reach production.
"""

import os
import sys
import unittest
from unittest.mock import MagicMock, patch

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


class TestPyTorchAPICompatibility(unittest.TestCase):
    """Test PyTorch API compatibility."""

    def test_scaled_dot_product_attention_api(self):
        """Test that we don't try to set invalid attributes on PyTorch functions."""
        try:
            import torch.nn.functional as F
        except ImportError:
            self.skipTest("PyTorch not available")

        # Test that scaled_dot_product_attention is a function, not an object with _enabled
        if hasattr(F, "scaled_dot_product_attention"):
            # This should be a function
            self.assertTrue(callable(F.scaled_dot_product_attention))

            # This should NOT have an _enabled attribute
            self.assertFalse(
                hasattr(F.scaled_dot_product_attention, "_enabled"),
                "scaled_dot_product_attention should not have _enabled attribute",
            )

            # Attempting to set _enabled should raise an AttributeError
            with self.assertRaises(AttributeError):
                F.scaled_dot_product_attention._enabled = True

    def test_compute_embeddings_bulk_no_invalid_pytorch_calls(self):
        """Test that compute_embeddings_bulk doesn't make invalid PyTorch API calls."""
        # Mock PyTorch modules to detect invalid calls
        with patch("torch.nn.functional") as mock_functional:
            # Create a mock scaled_dot_product_attention function
            mock_sdpa = MagicMock()
            mock_functional.scaled_dot_product_attention = mock_sdpa

            # Mock other torch components
            with (
                patch("torch.cuda") as mock_cuda,
                patch("torch.backends.cudnn"),
                patch("torch.device") as mock_device,
            ):

                mock_cuda.is_available.return_value = True
                mock_cuda.amp = MagicMock()
                mock_device.return_value = MagicMock(type="cuda")

                # Import the function after mocking
                try:
                    from analysis.code_analysis import compute_embeddings_bulk

                    # Create minimal test inputs
                    snippets = ["test code snippet"]
                    tokenizer = MagicMock()
                    tokenizer.return_value = {
                        "input_ids": MagicMock(),
                        "attention_mask": MagicMock(),
                    }

                    model = MagicMock()
                    model.eval.return_value = model
                    model.return_value = MagicMock(last_hidden_state=MagicMock())

                    device = MagicMock(type="cuda")
                    batch_size = 1

                    # This should NOT attempt to set _enabled on the function
                    try:
                        compute_embeddings_bulk(snippets, tokenizer, model, device, batch_size)
                    except Exception as e:
                        # If it fails, it shouldn't be due to trying to set _enabled
                        self.assertNotIn("_enabled", str(e))
                        self.assertNotIn(
                            "'builtin_function_or_method' object has no attribute '_enabled'",
                            str(e),
                        )

                except ImportError:
                    self.skipTest("Could not import compute_embeddings_bulk")

    def test_torch_backends_cuda_usage(self):
        """Test that we use PyTorch backends correctly."""
        try:
            import torch
        except ImportError:
            self.skipTest("PyTorch not available")

        # Test that we can access backends without errors
        if hasattr(torch, "backends"):
            backends = torch.backends

            # Test CUDA backend access
            if hasattr(backends, "cuda"):
                cuda_backend = backends.cuda

                # These should be available for controlling SDPA backends
                expected_attrs = [
                    "flash_sdp_enabled",
                    "mem_efficient_sdp_enabled",
                    "math_sdp_enabled",
                ]

                for attr in expected_attrs:
                    if hasattr(cuda_backend, attr):
                        # Should be callable functions
                        self.assertTrue(callable(getattr(cuda_backend, attr)))

    def test_flash_attention_detection(self):
        """Test Flash Attention detection logic."""
        try:
            import torch
            import torch.nn.functional as F
        except ImportError:
            self.skipTest("PyTorch not available")

        # Test that we can detect if scaled_dot_product_attention is available
        has_sdpa = hasattr(F, "scaled_dot_product_attention")

        if has_sdpa:
            # Should be a function
            self.assertTrue(callable(F.scaled_dot_product_attention))

            # Test that the function signature makes sense
            func = F.scaled_dot_product_attention

            # Should not raise when called properly (this is a basic smoke test)
            try:
                # Create minimal tensors for testing
                if torch.cuda.is_available():
                    device = "cuda"
                else:
                    device = "cpu"

                q = torch.randn(1, 1, 4, 8, device=device)
                k = torch.randn(1, 1, 4, 8, device=device)
                v = torch.randn(1, 1, 4, 8, device=device)

                # This should work without errors
                result = func(q, k, v)
                self.assertIsInstance(result, torch.Tensor)

            except Exception as e:
                # If it fails, it shouldn't be due to API misuse
                self.assertNotIn("_enabled", str(e))

    def test_device_tensor_to_numpy_compatibility(self):
        """Test that tensors are properly moved to CPU before numpy conversion."""
        try:
            import torch
        except ImportError:
            self.skipTest("PyTorch not available")

        # Test different device types
        devices_to_test = ["cpu"]

        if torch.cuda.is_available():
            devices_to_test.append("cuda")

        if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            devices_to_test.append("mps")

        for device_name in devices_to_test:
            with self.subTest(device=device_name):
                device = torch.device(device_name)

                # Create a tensor on the device
                tensor = torch.randn(2, 3, device=device)

                # Test proper conversion to numpy
                if device.type in ["cuda", "mps"]:
                    # Should move to CPU first
                    cpu_tensor = tensor.cpu()
                    numpy_array = cpu_tensor.numpy()
                else:
                    # CPU tensors can convert directly
                    numpy_array = tensor.numpy()

                # Verify conversion worked
                self.assertEqual(numpy_array.shape, (2, 3))

                # Test the pattern our code uses
                if device.type in ["cuda", "mps"]:
                    tensor = tensor.cpu()

                # This should never fail regardless of original device
                try:
                    result = tensor.numpy()
                    self.assertIsNotNone(result)
                except Exception as e:
                    self.fail(f"Failed to convert {device_name} tensor to numpy: {e}")


if __name__ == "__main__":
    unittest.main()
