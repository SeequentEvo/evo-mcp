# Blob Name Comparison Logic

The duplicate check does not compare the full object JSON. It fetches each object, reads `links.data`, and uses the blob identifier from each link as the comparison key. In the current code that identifier is taken from `link.name`, with `link.id` used as a fallback if `name` is missing.

## What Gets Read From Each Object

For each object, the script looks at the `links.data` collection.

Example:

```json
{
  "object": {
    "id": "obj-1",
    "name": "Pointset A"
  },
  "links": {
    "data": [
      {"name": "blob-a"},
      {"name": "blob-b"},
      {"name": "blob-c"}
    ]
  }
}
```

From that object, the comparison input becomes:

```json
["blob-a", "blob-b", "blob-c"]
```

## How Two Objects Are Compared

Assume two objects produce these blob-name lists:

- Object 1: `blob-a`, `blob-b`, `blob-c`
- Object 2: `blob-b`, `blob-c`, `blob-d`

The shared blob names are:

- `blob-b`
- `blob-c`

So those two objects are considered related because they reference some of the same blobs.

If two objects have no shared blob names, they are not reported as a duplicate pair.

## How The Matching Works Internally

The script builds an index from blob name to the objects that reference it.

Using the example above, the index is effectively:

```json
{
  "blob-a": ["obj-1"],
  "blob-b": ["obj-1", "obj-2"],
  "blob-c": ["obj-1", "obj-2"],
  "blob-d": ["obj-2"]
}
```

Only blob names that appear in more than one object contribute to matching.

That means:

- `blob-a` does not contribute to a duplicate pair
- `blob-d` does not contribute to a duplicate pair
- `blob-b` adds one shared-blob count for the pair `(obj-1, obj-2)`
- `blob-c` adds another shared-blob count for the pair `(obj-1, obj-2)`

Final result for that pair:

```json
{
  "pair": ["obj-1", "obj-2"],
  "shared_blob_count": 2
}
```

## How The Overlap Percentage Is Derived

The report also shows `Blob Overlap %`, which is based on blob-name sets.

Formula:

`Blob Overlap % = shared blobs / (blobs in object 1 + blobs in object 2 - shared blobs) * 100`

For the example above:

- Object 1 blobs = `3`
- Object 2 blobs = `3`
- Shared blobs = `2`
- Union of blob names = `4`

So the overlap is `2 / 4 * 100 = 50%`.

## Important Limitation

This comparison is entirely based on shared blob names.

- If two objects point to the same blob names, they can be reported as duplicates.
- If two objects are logically identical but do not share blob names, this script will not match them.
