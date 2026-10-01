import sqlite3
import json
import subprocess
import time
import os

db_path = r"C:\Users\strel\.n8n\database.sqlite"
repo_wf_path = r"C:\Users\strel\.gemini\antigravity\scratch\jobhunter-ai\workflows\hh_jobhunter_workflow.json"

# 1. Stop n8n processes
print("Stopping n8n node processes...")
subprocess.run(["powershell", "-Command", "Stop-Process -Name node -Force -ErrorAction SilentlyContinue"], capture_output=True)
time.sleep(2)

# 2. Read new nodes from repo JSON
with open(repo_wf_path, "r", encoding="utf-8") as f:
    wf_json = json.load(f)

new_nodes = wf_json["nodes"]
new_nodes_str = json.dumps(new_nodes, ensure_ascii=False)

# 3. Update SQLite database
conn = sqlite3.connect(db_path)
cur = conn.cursor()

# Check current active version
cur.execute("SELECT versionId, activeVersionId FROM workflow_entity WHERE id = 'PMmCjg4AL0rXpVqO'")
row = cur.fetchone()
print("workflow_entity versions before:", row)
v_id = row[0]
act_v_id = row[1] or v_id

# Update workflow_entity
cur.execute("UPDATE workflow_entity SET nodes = ? WHERE id = 'PMmCjg4AL0rXpVqO'", (new_nodes_str,))
print(f"Updated workflow_entity PMmCjg4AL0rXpVqO nodes.")

# Update workflow_history for this workflow
cur.execute("UPDATE workflow_history SET nodes = ? WHERE workflowId = 'PMmCjg4AL0rXpVqO'", (new_nodes_str,))
print(f"Updated workflow_history for workflowId PMmCjg4AL0rXpVqO (rows affected: {cur.rowcount}).")

# Update workflow_published_version
cur.execute("SELECT publishedVersionId FROM workflow_published_version WHERE workflowId = 'PMmCjg4AL0rXpVqO'")
pub_row = cur.fetchone()
print("workflow_published_version before:", pub_row)

conn.commit()

# Verify no occurrences of old code in workflow_history or workflow_entity
cur.execute("SELECT count(*) FROM workflow_history WHERE nodes LIKE '%effectiveTo && effectiveTo < 100000%'")
print("Occurrences of old code in workflow_history after update:", cur.fetchone()[0])

cur.execute("SELECT count(*) FROM workflow_entity WHERE nodes LIKE '%effectiveTo && effectiveTo < 100000%'")
print("Occurrences of old code in workflow_entity after update:", cur.fetchone()[0])

conn.close()

# 4. Start n8n via scheduled task
print("Starting n8n scheduled task...")
subprocess.run(["powershell", "-Command", "Start-ScheduledTask -TaskName 'JobHunter_N8N'"], capture_output=True)
time.sleep(5)
print("n8n restart requested.")
