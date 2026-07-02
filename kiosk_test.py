# import asyncio

# from kasa import SmartPlug

# KASA_PLUG_IP = "192.168.50.146"  # your discovered IP

# ALLOW_ON = {"251363580"}
# FORCE_OFF = {"251363720"}
# UNKNOWN_DEFAULT_OFF = True


# def decide(student_id: str) -> str:
#     if student_id in FORCE_OFF:
#         return "OFF"
#     if student_id in ALLOW_ON:
#         return "ON"
#     return "OFF" if UNKNOWN_DEFAULT_OFF else "IGNORE"


# async def set_plug(plug: SmartPlug, on: bool) -> None:
#     await plug.update()
#     if on:
#         await plug.turn_on()
#         print("Plug turned ON")
#     else:
#         await plug.turn_off()
#         print("Plug turned OFF")


# async def main():
#     plug = SmartPlug(KASA_PLUG_IP)

#     print("Kasa Control Running")
#     print("Scan/Type ID then press Enter. Type 'quit' to exit.\n")

#     while True:
#         student_id = input("Student ID> ").strip()

#         if not student_id:
#             continue
#         if student_id.lower() == "quit":
#             break

#         action = decide(student_id)
#         print(f"Scanned: {student_id} → {action}")

#         if action == "ON":
#             await set_plug(plug, True)
#         elif action == "OFF":
#             await set_plug(plug, False)
#         else:
#             print("…ignored")


# if __name__ == "__main__":
#     asyncio.run(main())
