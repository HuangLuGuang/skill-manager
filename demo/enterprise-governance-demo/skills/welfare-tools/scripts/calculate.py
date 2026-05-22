import argparse

def calculate_payment(principal, rate, years):
    monthly_rate = rate / 100 / 12
    num_payments = years * 12
    payment = (principal * monthly_rate) / (1 - (1 + monthly_rate)**-num_payments)
    return payment

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--principal", type=float, required=True)
    parser.add_argument("--rate", type=float, required=True)
    parser.add_argument("--years", type=int, required=True)
    args = parser.parse_args()
    
    result = calculate_payment(args.principal, args.rate, args.years)
    print(f"Monthly Payment: ${result:.2f}")
