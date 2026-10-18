from app.graph import get_system_overview, find_system_experts

system_id = "system-checkout"

overview = get_system_overview(system_id)
experts = find_system_experts(system_id)

print("SYSTEM OVERVIEW")
print(overview)

print("\nRELATED EXPERTS")
print(experts)
