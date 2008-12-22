from Tkinter import *
import tkSimpleDialog, tkFileDialog
import os, sys, ConfigParser

class EditShare(tkSimpleDialog.Dialog):

    def __init__(self, parent, title=None, name='', path='', plugin=''):
        self.name = name
        self.path = path
        self.plugin = StringVar()
        self.plugin.set(plugin)
        tkSimpleDialog.Dialog.__init__(self, parent, title)

    def get_dir(self):
        self.e2.delete(0, END)
        self.e2.insert(0, os.path.normpath(tkFileDialog.askdirectory()))

    def body(self, master):
        Label(master, text="Name:").grid(row=0)
        Label(master, text="Path:").grid(row=1)

        self.e1 = Entry(master)
        self.e2 = Entry(master)

        if self.name:
            self.e1.insert(0, self.name)
        if self.path:
            self.e2.insert(0, self.path)

        browse = Button(master, text="Browse", command=self.get_dir)

        self.e1.grid(row=0, column=1, columnspan=2, sticky=W+E)
        self.e2.grid(row=1, column=1, sticky=W+E)
        browse.grid(row=1, column=2)

        if not self.plugin.get():
            self.plugin.set('video')

        for i, name in zip(xrange(3), ('video', 'music', 'photo')):
            b = Radiobutton(master, text=name, variable=self.plugin, 
                value=name).grid(row=i, column=3)

        return self.e1 # initial focus

    def apply(self):
        name = self.e1.get()
        path = self.e2.get()
        self.result = name, path, self.plugin.get()

class pyTivoConfigurator(Frame):

    section = None
        
    def buildContainerList(self):
        header = Frame(self)
        header.pack(fill=X)
        Label(header, text='Shares').pack(side=LEFT)
        frame = Frame(self)
        frame.pack(fill=BOTH, expand=1)
        scrollbar = Scrollbar(frame, orient=VERTICAL)
        self.container_list = Listbox(frame, yscrollcommand=scrollbar.set)
        scrollbar.config(command=self.container_list.yview)
        scrollbar.pack(side=RIGHT, fill=Y)
        self.container_list.pack(side=LEFT, fill=BOTH, expand=1)
        self.container_list.bind("<Double-Button-1>", self.selected)

    def selected(self, e):
        if not self.container_list.curselection(): 
            return
        index = self.container_list.curselection()[0]
        self.section = self.container_list.get(index)

        self.edit()

    def buildButtons(self):
        frame = Frame(self)
        frame.pack(fill=X)

        quit_button = Button(frame, text="Quit", command=self.quit)
        quit_button.pack(side=RIGHT)

        del_button = Button(frame, text='Del', command=self.delete)
        del_button.pack(side=RIGHT)

        add_button = Button(frame, text="Add", command=self.add)
        add_button.pack(side=RIGHT)

        if sys.platform == 'win32':
            restart_button = Button(frame, text="Restart pyTivo",
                                    command=self.restart)
            restart_button.pack(side=RIGHT)

    def add(self):
        share = EditShare(self, title='New Share')
        if share.result:
            sharename, path, plugin = share.result
            self.config.add_section(sharename)
            self.config.set(sharename, 'type', plugin)
            self.config.set(sharename, 'path', path)
            self.updateContainerList()

    def delete(self):
        if not self.container_list.curselection(): 
            return
        index = self.container_list.curselection()[0]
        section = self.container_list.get(index)
        self.config.remove_section(section)
        self.updateContainerList()

    def restart(self):
        import win32serviceutil
        self.writeConfig()
        win32serviceutil.RestartService('pyTivo')

    def edit(self):
        if not self.section:
            return

        name = self.section
        path = self.config.get(name, 'path')
        plugin = self.config.get(name, 'type')

        share = EditShare(self, title='Edit Share', name=name, path=path,
                          plugin=plugin)
        if share.result:
            name, path, plugin = share.result
            if name != self.section:
                self.config.remove_section(self.section)
                self.config.add_section(name)
                self.section = name
            self.config.set(name, 'type', plugin)
            self.config.set(name, 'path', path)
            self.updateContainerList()

    def updateContainerList(self):
        self.writeConfig()
        self.container_list.delete(0, END)
        for section in self.config.sections():
            if not section == 'Server':
                self.container_list.insert(END, section)

    def readConfig(self):
        self.config = ConfigParser.ConfigParser()
        self.config.read(self.config_file)

    def writeConfig(self):
        self.config.write(open(self.config_file, 'w'))

    def __init__(self, master=None):
        Frame.__init__(self, master)
        self.master.title('pyTivoConfigurator')
        self.pack(fill=BOTH, expand=1)

        p = os.path.dirname(__file__)
        self.config_file = os.path.join(p, 'pyTivo.conf')

        self.readConfig()

        self.buildContainerList()
        self.buildButtons()

        self.updateContainerList()

if __name__ == '__main__':
    root = Tk()
    app = pyTivoConfigurator(master=root)
    app.mainloop()
