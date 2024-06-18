from config import bot

if __name__ == "__main__":
    gui = gui.botGUI

    # Run the bot in a separate thread to avoid blocking the GUI
    bot_thread = threading.Thread(target=lambda: bot.run('BOT_TOKEN'))
    bot_thread.start()

    gui.mainloop()