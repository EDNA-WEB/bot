import json
import os
from bs4 import BeautifulSoup
import requests

URL = "https://example.com/stranka-ktoru-sledujes" # Sem neskôr napíš web, ktorý chceš sledovať
DATA_FILE = "data.json"

def main():
    try:
        response = requests.get(URL)
        soup = BeautifulSoup(response.text, 'html.parser')
        # Príklad: hľadáme text v elemente <span id="cena">
        element = soup.find(id="cena")
        new_value = element.text.strip() if element else "Nenájdené"
    except Exception as e:
        print(f"Chyba: {e}")
        return

    old_value = None
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
            old_value = data.get('value')

    if new_value != old_value:
        print(f"Zmena! Stará: {old_value} -> Nová: {new_value}")
        with open(DATA_FILE, 'w', encoding='utf-8') as f:
            json.dump({"value": new_value}, f, ensure_ascii=False, indent=4)
    else:
        print("Žiadna zmena.")

if __name__ == "__main__":
    main()
