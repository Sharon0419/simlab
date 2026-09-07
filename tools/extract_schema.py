"""Build a field-accurate schema from the user's installed SIMLOX dictionary."""
import csv
import hashlib
import json
from pathlib import Path

SOURCE = Path(r'C:\Program Files\Systecon\SIMLOX\UserDoc\Table relations\DatabaseDictionary_SIMLOX.txt')
TARGET = Path(__file__).resolve().parents[1] / 'simlab' / 'data' / 'schema.json'

def main():
    raw = SOURCE.read_bytes()
    tables = {}
    for row in csv.DictReader(raw.decode('utf-8-sig').splitlines(), delimiter=';'):
        name = row['Table name:']
        tables.setdefault(name, []).append({
            'id': row['Column ID:'], 'order': int(row['Sequence:']),
            'description': row['Description:'], 'kind': row['Column Type:'],
            'type': row['Data Type:'], 'unit': row['Base Unit:'],
            'default': row['Default Value:'], 'constraints': row['Constraints:'],
            'references': row['Relates to:'],
        })
    result = {'format': 1, 'source': str(SOURCE), 'source_sha256': hashlib.sha256(raw).hexdigest(),
              'baseline': 'SIMLOX 2017（依据本机安装的官方数据字典）', 'tables': tables}
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    TARGET.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'{len(tables)} tables; {sum(map(len,tables.values()))} fields -> {TARGET}')

if __name__ == '__main__':
    main()
