
import sys
import torchvision.transforms.functional as F

# Mock the missing functional_tensor module if it doesn't exist
try:
    import torchvision.transforms.functional_tensor as F_t
except ImportError:
    # Create a dummy module
    from types import ModuleType
    F_t = ModuleType('torchvision.transforms.functional_tensor')
    sys.modules['torchvision.transforms.functional_tensor'] = F_t

# Add the missing function
if not hasattr(F_t, 'rgb_to_grayscale'):
    F_t.rgb_to_grayscale = F.rgb_to_grayscale
