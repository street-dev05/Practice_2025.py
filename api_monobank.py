import json
from datetime import datetime
from requests import get

def get_current_time():
    """Get current time in a readable format."""
    return datetime.now().strftime("%B %d %H:%M:%S")

def fetch_currency_data():
    """Fetch currency data from Monobank API and save to currency.json."""
    try:
        response = get("https://api.monobank.ua/bank/currency", timeout=5)
        data = response.json()
        
        if isinstance(data, dict) and "errorDescription" in data:
            print(f"{get_current_time()}: Error - {data['errorDescription']}")
            return False
            
        with open("currency.json", "w") as f:
            json.dump(data, f)
        print(f"{get_current_time()}: Data saved successfully")
        return True
    except Exception as e:
        print(f"{get_current_time()}: Failed to fetch data - {str(e)}")
        return False

def show_currency_rates():
    """Read currency.json and print USD and EUR rates."""
    try:
        with open("currency.json", "r") as f:
            data = json.load(f)
        
        usd_data = None
        eur_data = None
        for item in data:
            if item.get("currencyCodeA") == 840:
                usd_data = item
            elif item.get("currencyCodeA") == 978:
                eur_data = item
        
        if not usd_data or not eur_data:
            return "Error: Could not find USD or EUR rates"
            
        result = "Купівля/Продаж"
        result += f"\nUSD: {usd_data['rateBuy']}/{usd_data['rateSell']}"
        result += f"\nEUR: {eur_data['rateBuy']}/{eur_data['rateSell']}"
        return result
    except FileNotFoundError:
        return "Error: currency.json not found"
    except Exception as e:
        return f"Error: Failed to read data - {str(e)}"

def main():
    """Main function to run the program."""
    print(f"{get_current_time()}: Starting program")
    if fetch_currency_data():
        print(show_currency_rates())
    else:
        print("Could not fetch currency data")

if __name__ == "__main__":
    main()
