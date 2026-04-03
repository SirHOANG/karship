# Karship K# discord + web helper demo
let bot = discord.create("!")
bot.command("ping", "pong")
bot.command("hello", "hi from karship")

spark("!ping =>", bot.simulate("!ping"))
spark("!hello =>", bot.simulate("!hello"))

let page = web.page("Karship", "<h1>K# is online</h1><p>Full-stack mode initialized.</p>")
spark("Web page output:")
spark(page)
spark("Runtime profile:", memory.profile()["mode"], memory.profile()["total_ram_gb"], "GB")
