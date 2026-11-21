from recursivecal import RecursiveCalEnv, policy_calibration

env = RecursiveCalEnv(seed=900003)
print("Available diagnostics:", ", ".join(env.available_actions()))
cal = policy_calibration(env, "greedy")
for obs in env.records:
    print("Observed:", obs)
print("Chosen calibration:", cal)
print("Frozen evaluator result:", env.finish(cal))
