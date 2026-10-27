import csv
import random
from datetime import datetime, timedelta

def generate_synthetic_data(filename="synthetic_transactions.csv", num_records=1000):
    property_types = ["HDB", "Condo", "Landed"]
    towns = ["Bedok", "Tampines", "Clementi", "Jurong East", "Punggol", "Bukit Merah"]
    
    with open(filename, mode="w", newline="") as file:
        writer = csv.writer(file)
        writer.writerow([
            "property_type", "postal_code", "block", "street_name", 
            "town", "floor_area_sqm", "lease_commence_date", 
            "resale_price", "transaction_date", "lat", "lng"
        ])
        
        for _ in range(num_records):
            p_type = random.choice(property_types)
            town = random.choice(towns)
            
            # Constraints based on property type
            if p_type == "HDB":
                floor_area = round(random.uniform(60, 130), 1)
                base_price = 500000
                lease_start = random.randint(1980, 2018)
            elif p_type == "Condo":
                floor_area = round(random.uniform(40, 200), 1)
                base_price = 1200000
                lease_start = random.randint(1990, 2022)
            else:
                floor_area = round(random.uniform(150, 500), 1)
                base_price = 3000000
                lease_start = random.randint(1970, 2020)
                
            price = round(base_price * (floor_area / 100) * random.uniform(0.8, 1.2))
            
            # Fake coordinates in Singapore bounding box
            lat = round(random.uniform(1.25, 1.45), 6)
            lng = round(random.uniform(103.65, 104.0), 6)
            
            date = datetime.now() - timedelta(days=random.randint(0, 365*3))
            
            writer.writerow([
                p_type,
                f"{random.randint(10,80):02d}{random.randint(1000,9999)}",
                f"{random.randint(1, 999)}{random.choice(['A','B','',''])}",
                f"Virtual Street {random.randint(1, 100)}",
                town,
                floor_area,
                lease_start,
                price,
                date.strftime("%Y-%m-%d"),
                lat,
                lng
            ])
            
    print(f"Successfully generated {num_records} synthetic records in {filename}.")

if __name__ == "__main__":
    generate_synthetic_data()
