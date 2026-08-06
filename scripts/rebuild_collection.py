from backend.store.milvus_store import client, COLLECTION, create_collection

# 1. 先 drop 旧的(空库,无损失)
if client.has_collection(COLLECTION):
    client.drop_collection(COLLECTION)
    print(f"dropped old collection: {COLLECTION}")

# 2. 用新 schema 重建
create_collection()
print(f"recreated: {COLLECTION}")

# 3. 验证 text 字段的 analyzer 已挂上
desc = client.describe_collection(COLLECTION)
for f in desc["fields"]:
    if f["name"] == "text":
        print("text field params:", f.get("params"))
