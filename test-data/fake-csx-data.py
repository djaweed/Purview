import csv
from faker import Faker
import random

# Initialize Faker instance
fake = Faker()

# Define a function to generate fake credit card numbers
def generate_credit_card():
    card_types = ['visa', 'mastercard', 'discover', 'amex']  # Use lowercase for Faker
    card_type = random.choice(card_types)
    
    # Generate the credit card number for the selected type
    cc_number = fake.credit_card_number(card_type=card_type)
    expiry_date = fake.credit_card_expire()
    
    return card_type.capitalize(), cc_number, expiry_date  # Capitalize card type for display

# List to store customer data
data = []

# Generate 2500 fake customer records
for _ in range(2500):
    first_name = fake.first_name()
    last_name = fake.last_name()
    email = fake.email()
    phone = fake.phone_number()
    address = fake.street_address()
    city = fake.city()
    state = fake.state()
    zip_code = fake.zipcode()
    country = fake.country()
    card_type, cc_number, expiry_date = generate_credit_card()
    
    # Add the row to the data list
    customer_row = [
        fake.uuid4(),  # Random unique CustomerID
        first_name,
        last_name,
        email,
        phone,
        address,
        city,
        state,
        zip_code,
        country,
        f"{first_name} {last_name}",  # Full Name
        cc_number,
        card_type,
        expiry_date
    ]
    
    data.append(customer_row)

# Define the header for the CSV file
header = [
    'CustomerID', 'FirstName', 'LastName', 'Email', 'Phone', 'StreetAddress', 'City', 'State', 'ZipCode', 'Country',
    'FullName', 'CreditCardNumber', 'CreditCardType', 'ExpiryDate'
]

# Write the data to a CSV file
with open('fake_customer_data2.csv', 'w', newline='') as csvfile:
    writer = csv.writer(csvfile)
    writer.writerow(header)
    writer.writerows(data)

print("CSV file 'fake_customer_data.csv' has been created with 2500 rows.")
