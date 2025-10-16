#!/usr/bin/env python3
"""
Example usage of extracted chair classes
"""

import sys
from pathlib import Path

# Add the output directory to path
output_dir = Path(__file__).parent
sys.path.insert(0, str(output_dir))

def demonstrate_chair_usage():
    """Demonstrate how to use the extracted chair classes"""
    print("Extracted chair classes created successfully!")
    print("\nTo use the extracted chairs:")
    print("1. Import the generated factory classes")
    print("2. Create instances with factory_seed parameter")
    print("3. Call create_asset() to generate the chair")
    print("\nExample:")
    print("from chair042 import Chair042Factory")
    print("factory = Chair042Factory(factory_seed=42)")
    print("chair = factory.create_asset()")
    print("info = factory.get_geometry_info()")
    print("print(f'Chair dimensions: {{info["dimensions"]}}')")

if __name__ == "__main__":
    demonstrate_chair_usage()
