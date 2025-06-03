#!/usr/bin/env python3
"""
Smart Number Cut Length Calculator - SS-FV Cases Only (Simplified)
Simple logic for SS-FV part numbers only
"""

import json
import csv
import math
import re
from dataclasses import dataclass
from typing import Dict, List
from pathlib import Path


@dataclass
class BOMItem:
    item_number: int
    part_number: str
    value: float
    unit: str = "EA"


@dataclass
class ProductionTimeItem:
    operation: str
    time_minutes: float
    operation_number: str = ""


class SmartNumberCalculator:
    """Simple calculator for SS-FV format part numbers only."""
    
    HP_ADJUSTMENT = 4.0
    
    def __init__(self, output_directory: str = "output"):
        """Initialize calculator with output directory."""
        self.output_dir = Path(output_directory)
        self.output_dir.mkdir(exist_ok=True)
        
        # Size-specific constants
        self.size_constants = {
            "08": {"base_reduction": 2 * 2.971, "base_addition": 2 * 0.221, "convolution": 2 * 0.371},
            "12": {"base_reduction": 2 * 2.973, "base_addition": 2 * 0.318, "convolution": 2 * 0.452},
            "16": {"base_reduction": 2 * 2.974, "base_addition": 2 * 0.4115, "convolution": 2 * 0.457}
        }
        
        # BOM templates
        self.bom_templates = {
            "SS-FV08_STD": [
                {"part_number": "H008", "type": "length1"},
                {"part_number": "BB003", "value": 2, "type": "constant"},
                {"part_number": "HF004", "value": 2, "type": "constant"},
                {"part_number": "CS007", "type": "length1_minus", "minus_value": 7},
                {"part_number": "H013", "type": "length1_minus", "minus_value": 3.5},
                {"part_number": "CF003", "value": 2, "type": "constant"},
                {"part_number": "HTB-255K", "value": 0.071, "type": "constant"}
            ],
            "SS-FV08_MLI": [
                {"part_number": "H008", "type": "length1"},
                {"part_number": "BB003", "value": 2, "type": "constant"},
                {"part_number": "HF004", "value": 2, "type": "constant"},
                {"part_number": "MI001", "type": "length1_minus_times6", "minus_value": 7},
                {"part_number": "MR001", "type": "length1_minus_times6", "minus_value": 7},
                {"part_number": "CS010", "type": "length1_minus", "minus_value": 7},
                {"part_number": "H016", "type": "length1_minus", "minus_value": 3.5},
                {"part_number": "CF009", "value": 2, "type": "constant"},
                {"part_number": "HTB-255K", "value": 0.071, "type": "constant"}
            ],
            "SS-FV12_STD": [
                {"part_number": "H011","type": "length1"},
                {"part_number": "BB004", "value": 2, "type": "constant"},
                {"part_number": "HF005", "value": 2, "type": "constant"},
                {"part_number": "CS010", "type": "length1_minus", "minus_value": 7},
                {"part_number": "H016", "type": "length1_minus", "minus_value": 3.5},
                {"part_number": "CF004", "value": 2, "type": "constant"},
                {"part_number": "HTB-255K", "value": 0.071, "type": "constant"}
            ],
            "SS-FV12_MLI": [
                {"part_number": "H011", "type": "length1"},
                {"part_number": "BB004", "value": 2, "type": "constant"},
                {"part_number": "HF005", "value": 2, "type": "constant"},
                {"part_number": "MI002", "type": "length1_minus_times6", "minus_value": 7},
                {"part_number": "MR002", "type": "length1_minus_times6", "minus_value": 7},
                {"part_number": "CS010", "type": "length1_minus", "minus_value": 7},
                {"part_number": "H022", "type": "length1_minus", "minus_value": 3.5},
                {"part_number": "CF010", "value": 2, "type": "constant"},
                {"part_number": "HTB-255K", "value": 0.071, "type": "constant"}
            ],
            "SS-FV16_STD": [
                {"part_number": "H014", "type": "length1"},
                {"part_number": "BB005", "value": 2, "type": "constant"},
                {"part_number": "HF006", "value": 2, "type": "constant"},
                {"part_number": "CS010", "type": "length1_minus", "minus_value": 7},
                {"part_number": "H019", "type": "length1_minus", "minus_value": 3.5},
                {"part_number": "CF005", "value": 2, "type": "constant"},
                {"part_number": "HTB-255K", "value": 0.071, "type": "constant"}
            ],
            "SS-FV16_MLI": [
                {"part_number": "H014", "type": "length1"},
                {"part_number": "BB005", "value": 2, "type": "constant"},
                {"part_number": "HF006", "value": 2, "type": "constant"},
                {"part_number": "MI003", "type": "length1_minus_times6", "minus_value": 7},
                {"part_number": "MR003", "type": "length1_minus_times6", "minus_value": 7},
                {"part_number": "CS010", "type": "length1_minus", "minus_value": 7},
                {"part_number": "H022", "type": "length1_minus", "minus_value": 3.5},
                {"part_number": "CF011", "value": 2, "type": "constant"},
                {"part_number": "HTB-255K", "value": 0.071, "type": "constant"}
            ]
        }
            
        # Pricing formulas by case
        self.pricing_formulas = {
            "SS-FV08_STD": {
                "base_price": 137.33,
                "price_per_foot": 37.09
            },
            "SS-FV08_MLI": {
                "base_price": 147.61, 
                "price_per_foot": 52.62 
            },
            "SS-FV12_STD": {
                "base_price": 147.89,
                "price_per_foot": 44.32
            },
            "SS-FV12_MLI": {
                "base_price": 160.94, 
                "price_per_foot": 62.7 
            },
            "SS-FV16_STD": {
                "base_price": 151.40, 
                "price_per_foot": 50.62  
            },
            "SS-FV16_MLI": {
                "base_price": 163.65,
                "price_per_foot": 68.23
            }
        }
       
    def parse_part_number(self, part_number: str) -> Dict:
        """Parse SS-FV part number into components."""
        part_number = part_number.strip()
        
        # Check if it's SS-FV format
        if not part_number.startswith("SS-FV"):
            return {"error": "Not a valid SS-FV format"}
        
        # Determine size and pressure
        size = None
        pressure = "HP"  # Always HP for SS-FV
        
        if part_number.startswith("SS-FV8"):
            size = "08"
        elif part_number.startswith("SS-FV12"):
            size = "12"
        elif part_number.startswith("SS-FV16"):
            size = "16"
        else:
            return {"error": "Unknown SS-FV size"}
        
        # Determine performance from ending - check special cases first
        performance = None
        performance_suffix = ""
        
        if part_number.endswith(("0424", "0660", "0663")):
            performance = "MLI"
            performance_suffix = part_number[-4:]  # Last 4 characters
        elif part_number.endswith(("0658", "0662")):
            performance = "STD"
            performance_suffix = part_number[-4:]  # Last 4 characters
        elif part_number.endswith("1"):
            performance = "STD"
            performance_suffix = "1"
        elif part_number.endswith("2"):
            performance = "MLI"
            performance_suffix = "2"
        else:
            return {"error": "Invalid performance indicator (must end with 1, 2, or special codes: 0424, 0660, 0663, 0658, 0662)"}
        
        # Extract length - handle both normal and compressed formats
        parts = part_number.split("-")
        length_str = ""
        
        if len(parts) >= 3:
            # Check if parts[2] contains both length and performance (compressed format)
            length_and_performance = parts[2]
            
            # Use regex to find length pattern within the string
            # Pattern: digits followed by optional CM, anywhere in the string
            length_pattern = '(\\d+(?:CM|cm)?)'
            match = re.search(length_pattern, length_and_performance)
            
            if match:
                length_str = match.group(1)
            else:
                return {"error": f"Could not extract length from: {length_and_performance}"}
                
        elif len(parts) == 2:
            # Very compressed format - extract from the end of parts[1]
            # Example: SS-FV12TN12TN121800CM0424
            full_part = parts[1]
            
            # Remove performance suffix from the end first
            if full_part.endswith(performance_suffix):
                remaining = full_part[:-len(performance_suffix)]
                
                # Create expected base pattern based on size
                # Format: FV{size}TN{size}TN{size}
                expected_base = f"FV{size}TN{size}TN{size}"
                
                if remaining.startswith(expected_base):
                    # Extract everything after the expected base pattern
                    length_str = remaining[len(expected_base):]
                    
                    if not length_str:
                        return {"error": "No length found after base pattern"}
                else:
                    # Fallback: try to find length pattern at the end
                    length_pattern = '(\\d+(?:CM|cm)?)$'
                    match = re.search(length_pattern, remaining)
                    
                    if match:
                        length_str = match.group(1)
                    else:
                        return {"error": "Could not extract length from compressed format"}
            else:
                return {"error": "Invalid compressed format"}
        else:
            return {"error": "Invalid part number format - need at least 2 hyphens"}
        
        if not length_str:
            return {"error": "Could not extract length from part number"}
        
        # Check for CM and convert
        if "CM" in length_str.upper():
            length_cm = float(length_str.upper().replace("CM", ""))
            length = length_cm / 2.54  # Convert to inches
            length_unit = "cm_converted"
        else:
            try:
                length = float(length_str)
                length_unit = "inches"
            except ValueError:
                return {"error": f"Invalid length value: {length_str}"}
        
        return {
            "size": size,
            "pressure": pressure,
            "performance": performance,
            "length": length,
            "length_unit": length_unit
        }
    
    def round_up_to_sixteenth(self, value: float) -> float:
        """Round up to nearest 1/16 inch."""
        return math.ceil(value * 16) / 16
    
    def round_up_to_half_feet(self, inches: float) -> float:
        """Round up length to nearest 1/2 feet for pricing."""
        feet = inches / 12
        return math.ceil(feet / 0.5) * 0.5
    
    def round_up_to_minute(self, minutes: float) -> float:
        """Round up time to nearest minute."""
        return math.ceil(minutes)
    
    def calculate_overall_length(self, x: float) -> float:
        """Calculate overall length based on input length."""
        if x <= 48:
            result = x * 1.005
            return result
        elif x <= 120:
            result = x * 1.035
            return result
        elif x <= 360:
            result = x * 1.05
            return result
        else:
            result = x * 1.072
            return result
    
    def calculate_first_bom_value(self, length: float, size: str) -> float:
        """Calculate value for first BOM item (length1 type)."""
        if size not in self.size_constants:
            return 0
        
        constants = self.size_constants[size]
        
        # Use dynamic length multiplier based on length value
        overall_length = self.calculate_overall_length(length)
        
        # Formula: overall_length - base_reduction + base_addition + HP_adjustment + convolution
        value = (overall_length - 
                constants["base_reduction"] + 
                constants["base_addition"] + 
                self.HP_ADJUSTMENT + 
                constants["convolution"])
        
        return value
    
    def generate_bom(self, size: str, performance: str, length: float, quantity: int = 1) -> List[BOMItem]:
        """Generate BOM for the part."""
        bom_items = []
        
        bom_key = f"SS-FV{size}_{performance}"
        if bom_key not in self.bom_templates:
            return bom_items
        
        template = self.bom_templates[bom_key]
        first_item_value = self.calculate_first_bom_value(length, size)
        
        for i, item_template in enumerate(template):
            part_number = item_template["part_number"]
            item_type = item_template["type"]
            
            # Calculate value based on type
            if item_type == "length1":
                value = self.round_up_to_sixteenth(first_item_value) * quantity
                unit = "IN"
            elif item_type == "constant":
                value = item_template["value"] * quantity
                unit = "EA"
            elif item_type == "length1_minus":
                minus_val = item_template["minus_value"]
                value = self.round_up_to_sixteenth(first_item_value - minus_val) * quantity
                unit = "IN"
            elif item_type == "length1_minus_times6":
                # Special case for MI001, MR001: (H008 - 7) * 6
                minus_val = item_template["minus_value"]
                value = self.round_up_to_sixteenth((first_item_value - minus_val) * 6) * quantity
                unit = "IN"
            else:
                value = 1 * quantity
                unit = "EA"
            
            bom_item = BOMItem(
                item_number=i + 1,
                part_number=part_number,
                value=round(value, 3),
                unit=unit
            )
            bom_items.append(bom_item)
        
        return bom_items
    
    def calculate_pricing(self, length: float, size: str, performance: str) -> float:
        """Calculate pricing: base_price + (price_per_foot × length_rounded_to_half_feet)"""
        pricing_key = f"SS-FV{size}_{performance}"
        
        if pricing_key not in self.pricing_formulas:
            # Default fallback pricing
            length_half_feet = self.round_up_to_half_feet(length)
            return 137.33 + (37.09 * length_half_feet)
        
        pricing_config = self.pricing_formulas[pricing_key]
        length_half_feet = self.round_up_to_half_feet(length)
        
        return (pricing_config["base_price"] + 
                (pricing_config["price_per_foot"] * length_half_feet))
    
    def generate_description(self, size: str, pressure: str, performance: str, length: float) -> str:
        """Generate description in format: Size" HP Performance Length" Insulon Hose"""
        # Convert size code to fractional description
        size_map = {
            "08": '1/2"',
            "12": '3/4"', 
            "16": '1"'
        }
        
        size_desc = size_map.get(size, f'{size}"')
        return f'{size_desc} {pressure} {performance} {length:.0f}" Insulon Hose'
    
    def calculate_production_times(self, performance: str, length: float) -> List[ProductionTimeItem]:
        """Calculate production times for HP STD operations."""
        production_items = []
        
        if performance == "STD":
            # HP STD operations with formulas
            operations = [
                {
                    "name": "Insulon Hose Cutting and HP Inner SA",
                    "formula": lambda l: 25 + 0.17 * (l / 12),
                    "op_number": "65cba8e0011f783b09a277d6"
                },
                {
                    "name": "Insulon Hose Assembly", 
                    "formula": lambda l: 15 + 0.44 * (l / 12),
                    "op_number": "65cb9b47bd03e2f47a349719"
                },
                {
                    "name": "Insulon Hose Thermal Test",
                    "formula": lambda l: 7.5 + 0.09 * (l / 12),
                    "op_number": "65cb9d4cbd03e2f47a349796"
                },
                {
                    "name": "Insulon Hose QC and Laser Mark",
                    "formula": lambda l: 10 + 0.083 * (l / 12),
                    "op_number": "65cba2babd03e2f47a3498be"
                }
            ]
            
            for op in operations:
                time_minutes = op["formula"](length)
                production_items.append(ProductionTimeItem(
                    operation=op["name"],
                    time_minutes=self.round_up_to_minute(time_minutes),
                    operation_number=op["op_number"]
                ))
        
        # For MLI, add basic operations (can be expanded later)
        elif performance == "MLI":
            # HP MLI operations with formulas
            operations = [
                {
                    "name": "Insulon Hose Cutting and HP Inner SA",
                    "formula": lambda l: 25 + 0.17 * (l / 12),
                    "op_number": "65cba8e0011f783b09a277d6"
                },
                {
                    "name": "Insulon Hose Assembly w/ MLI", 
                    "formula": lambda l: 20 + 1.44 * (l / 12),
                    "op_number": "65d4d84db16fca47947176d3"
                },
                {
                    "name": "Insulon Hose Thermal Test",
                    "formula": lambda l: 7.5 + 0.09 * (l / 12),
                    "op_number": "65cb9d4cbd03e2f47a349796"
                },
                {
                    "name": "Insulon Hose QC and Laser Mark",
                    "formula": lambda l: 10 + 0.083 * (l / 12),
                    "op_number": "65cba2babd03e2f47a3498be"
                }
            ]
            for op in operations:
                time_minutes = op["formula"](length)
                production_items.append(ProductionTimeItem(
                    operation=op["name"],
                    time_minutes=self.round_up_to_minute(time_minutes),
                    operation_number=op["op_number"]
                ))
        return production_items
    
    def process_part_number(self, part_number: str, quantity: int = 1) -> Dict:
        """Process SS-FV part number and return results."""
        try:
            # Parse part number
            parsed = self.parse_part_number(part_number)
            if "error" in parsed:
                return parsed
            
            size = parsed["size"]
            pressure = parsed["pressure"]
            performance = parsed["performance"]
            length = parsed["length"]
            
            # Generate BOM
            bom_items = self.generate_bom(size, performance, length, quantity)
            
            # Calculate production times
            production_items = self.calculate_production_times(performance, length)
            
            # Calculate pricing
            unit_price = self.calculate_pricing(length, size, performance)
            total_price = unit_price * quantity
            
            # Get first BOM item value for reference (rounded)
            first_bom_value = self.round_up_to_sixteenth(self.calculate_first_bom_value(length, size)) if bom_items else 0
            
            # Generate description
            description = self.generate_description(size, pressure, performance, length)
            
            return {
                "part_number": part_number,
                "description": description,
                "size": size,
                "pressure": pressure,
                "performance": performance,
                "length": length,
                "length_unit": parsed["length_unit"],
                "first_bom_value": round(first_bom_value, 3),
                "bom_items": [item.__dict__ for item in bom_items],
                "bom_items_simple": {item.part_number: item.value for item in bom_items},  # For easy access
                "production_items": [item.__dict__ for item in production_items],
                "production_operations": {  # For easy access to operations
                    item.operation: {
                        "time_minutes": item.time_minutes,
                        "operation_number": item.operation_number
                    } for item in production_items
                },
                "quantity": quantity,
                "unit_price": round(unit_price, 2),
                "total_price": round(total_price, 2),
                "total_production_time": sum(item.time_minutes for item in production_items)
            }
            
        except Exception as e:
            return {"error": f"Error processing part number: {str(e)}"}


def export_to_csv(data: Dict, filename: str):
    """Export results to CSV."""
    if "error" in data:
        print(f"Cannot export: {data['error']}")
        return
    
    # Export BOM
    bom_filename = f"{filename}_bom.csv"
    with open(bom_filename, 'w', newline='') as f:
        if data['bom_items']:
            writer = csv.DictWriter(f, fieldnames=data['bom_items'][0].keys())
            writer.writeheader()
            writer.writerows(data['bom_items'])
    
    print(f"Exported BOM to {bom_filename}")


def main():
    """Main function."""
    import argparse
    
    parser = argparse.ArgumentParser(description="SS-FV Part Number Calculator")
    parser.add_argument("part_number", help="SS-FV part number to process")
    parser.add_argument("-q", "--quantity", type=int, default=1, help="Quantity (default: 1)")
    parser.add_argument("-o", "--output", help="Output file prefix")
    
    args = parser.parse_args()
    
    calculator = SmartNumberCalculator()
    result = calculator.process_part_number(args.part_number, args.quantity)
    
    if args.output:
        # Save JSON
        json_filename = f"{args.output}.json"
        with open(json_filename, 'w') as f:
            json.dump(result, f, indent=2)
        print(f"Results saved to {json_filename}")
        
        export_to_csv(result, args.output)
    else:
        # Print results
        if "error" in result:
            print(f"ERROR: {result['error']}")
        else:
            print(f"Part Number: {result['part_number']}")
            print(f"Size: {result['size']}, Pressure: {result['pressure']}, Performance: {result['performance']}")
            print(f"Length: {result['length']:.1f} {result['length_unit']}")
            print(f"First BOM Value: {result['first_bom_value']:.3f}")
            print(f"Unit Price: ${result['unit_price']:.2f}")
            print(f"Total Price: ${result['total_price']:.2f}")
            print(f"Total Production Time: {result['total_production_time']:.0f} minutes")
            
            print(f"\nBOM Items ({len(result['bom_items'])}):")
            for item in result['bom_items']:
                print(f"  {item['item_number']}: {item['part_number']} = {item['value']} {item['unit']}")
            
            print(f"\nProduction Operations:")
            for item in result['production_items']:
                op_num = f" [{item['operation_number']}]" if item['operation_number'] else ""
                print(f"  {item['operation']}{op_num}: {item['time_minutes']:.0f} min")


if __name__ == "__main__":
    # Check if running from command line with arguments     
    import sys     
    if len(sys.argv) > 1:         
        main()  # Run command line version     
    else:         
        # Running from IDE - ask user for part number         
        print("SS-FV Part Number Calculator")         
        print("=" * 40)                  
        
        try:             
            part_number = input("Enter SS-FV part number: ").strip()                          
            
            if not part_number:                 
                print("No part number entered. Exiting.")                 
                exit()                          
            
            print(f"\nProcessing: {part_number}")             
            print("-" * 40)                          
            
            calculator = SmartNumberCalculator()             
            result = calculator.process_part_number(part_number)                          
            
            if "error" in result:                 
                print(f"ERROR: {result['error']}")             
            else:                 
                print(f"Part Number: {result['part_number']}")                 
                print(f"Description: {result['description']}")                 
                print(f"Size: {result['size']}, Pressure: {result['pressure']}, Performance: {result['performance']}")                 
                print(f"Length: {result['length']:.1f} {result['length_unit']}")                 
                print(f"First BOM Value: {result['first_bom_value']:.3f}")                 
                print(f"Unit Price: ${result['unit_price']:.2f}")                 
                print(f"Total Price: ${result['total_price']:.2f}")                 
                print(f"Total Production Time: {result['total_production_time']:.0f} minutes")                                  
                
                print(f"\nBOM Items ({len(result['bom_items'])}):")                 
                for item in result['bom_items']:                     
                    print(f"  {item['item_number']}: {item['part_number']} = {item['value']} {item['unit']}")                                  
                
                print(f"\nProduction Operations:")                 
                for item in result['production_items']:                     
                    op_num = f" [{item['operation_number']}]" if item['operation_number'] else ""                     
                    print(f"  {item['operation']}{op_num}: {item['time_minutes']:.0f} min")
                              
        except KeyboardInterrupt:             
            print("\n\nExiting...")         
        except Exception as e:             
            print(f"\nUnexpected error: {e}")
            
        print("\nThank you for using the SS-FV Calculator!")
