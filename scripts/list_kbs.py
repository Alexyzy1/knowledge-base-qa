from backend.store.mysql_store import list_kb
kbs = list_kb()
for k in kbs:
    print("kb_id=%s  name=%s" % (k["id"], k["name"]))
