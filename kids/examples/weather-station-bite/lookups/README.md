# Lookup tables

Each `<name>.json` is a JSON object from a source value to a canonical value. A mapping refers to a table by its file stem:

```json
{ "from": "target_class", "to": "classification",
  "via": [{ "conversion": "lookup", "params": { "table": "<name>" } }] }
```

The key is the decoded value as text: the dictionary's label where the field has one (`"Rotary wing"`), the number otherwise (`"3"`). A value with no entry leaves the canonical field out.

`WX_message_classification.json` gives the Billie track class for each mapped message of the WX interface. The message set has no classification field: a `Position` report always describes the station itself, which is none of the aircraft, vehicle or clutter classes, so it maps to `other`.
