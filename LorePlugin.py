import os
import time
import sqlite3
import json
import Tkinter
import ttk
import tkMessageBox
import threading
import Queue

import jsonrpclib
from LoreClient import FixedFieldsTable, UserFieldsTable, Searchable


def __init__(self, LoreURL="http://drugsite-dev.msi.umn.edu/mmLore/jsonrpc"):
  self.menuBar.addmenuitem(
    'Plugin', 'command', 'Controller', label='TEST',
    command = lambda s=self, url=LoreURL: Controller(s, url))


class JSONRPCThread(threading.Thread):

  def __init__(self, rpc_server="", methodname="", queue=None, args=(), 
               kwargs={}):
    threading.Thread.__init__(self, group=None, target=self.request, name=None,
                              args=args, kwargs=kwargs)
    self.rpc_server = rpc_server
    self.methodname = methodname
    self.queue = queue

  def request(self, *args, **kwargs):
    rv = self.rpc_server._request(self.methodname, kwargs)
    if(type(rv) == list):
      rv = {"result": rv}
    rv["methodname"] = self.methodname
    self.queue.put(json.dumps(rv))
  

class MainThreadConsumer(object):
  _loop_sleep = 250

  def __init__(self, root=None):
    self.root = root
    self.queue = Queue.Queue()
    self.check_queue()
    self.methods = {}
    
  def check_queue(self):
    # Easiest method to use when using nonblocking get
    try:
      data = json.loads(self.queue.get_nowait())
      mthd = data.pop("methodname")
      self.methods[mthd](response=data)
    except Queue.Empty:
       pass

    self.root.after(self._loop_sleep, self.check_queue)


class LoreException(Exception):

  def __init__(self, msg=""):
    self.args = (msg,)

  def __str__(self):
    return " ".join(self.args)


def _jsonrpc_exception_dialog(E=None):
  if(not E): 
    return
  title = "%s.%s: %s" % (
    E.__class__.__module__, E.__class__.__name__, E.args[0])
  if(len(E.args) > 2):
    msg = E.args[2].replace("|", os.linesep)
  elif(len(E.args) == 2):
    msg = "%s: A server error has occured" % (E.args[1])
  else:
    msg = "A server error has occured"
  tkMessageBox.showerror(title=title, message=msg)


def _brutally_set_state(widget, state='disabled'):
  _klasses = set([Tkinter.Entry, Tkinter.Button, ttk.Entry, ttk.Button])
  if(widget.__class__ in _klasses):
    widget.config(state=state)
  for child in widget.winfo_children():
    _brutally_set_state(child, state=state)


class AutoScrollbar(ttk.Scrollbar):
  """An updated version of Fredrik Lundh's autohiding scrollbar 
  (http://effbot.org/zone/tkinter-autoscrollbar.htm)
  """

  def __init__(self, master=None, grid_row=0, grid_column=0, sticky="", **kw):
    ttk.Scrollbar.__init__(self, master, **kw)
    self.grid_kw = { "row": grid_row, "column": grid_column, "sticky": sticky }

  def set(self, low, high):
    if(float(low) <= 0.0 and float(high) >= 1.0):
      self.grid_forget()
    else:
      self.grid(**self.grid_kw)
    ttk.Scrollbar.set(self, low, high)

  def pack(self, **kw):
    raise Tkinter.TclError("Cannot use pack with this widget")

  def place(self, **kw):
    raise Tkinter.TclError("Cannot use place with this widget")


class ScrollingFrame(Tkinter.Canvas):
  """Setup a frame with autoscrollbars
  
  :param master: the master widget for the canvas
  :param xscroll: If true, put in a horizontal autoscrollbar 
  :param yscroll: If true, put in a vertical autoscrollbar
  :param label: If true, use a Labelframe instead of Frame
  :param style: If true, use to style the frame
  :param kw: keywords to pass to ttk.Canvas
  """

  def __init__(self, master=None, xscroll=False, yscroll=False, 
               label="", style="", **kw):
    Tkinter.Canvas.__init__(self, master, **kw)
    scrollbars = {
      "v": AutoScrollbar(master, grid_row=0, grid_column=1, sticky="ns"),
      "h": AutoScrollbar(master, grid_row=1, grid_column=0, sticky="ew"),
    }
    scrollbars["h"].config(orient=Tkinter.HORIZONTAL)

    if(xscroll):
      self.config(xscrollcommand=scrollbars["h"].set)
      scrollbars["h"].config(command=self.xview)
    if(yscroll):
      self.config(yscrollcommand=scrollbars["v"].set)
      scrollbars["v"].config(command=self.yview)

    # make the canvas expandable
    master.grid_rowconfigure(0, weight=1)
    master.grid_columnconfigure(0, weight=1)

    # Create a frame for the contents
    if(label):
      self.frame = ttk.Labelframe(self, text=label, style=style)
    else:
      self.frame = ttk.Frame(self, style=style)
    self.frame.rowconfigure(0, weight=1)
    self.frame.columnconfigure(0, weight=1)

    # Anchor the frame to the NW corner of the canvas
    self.create_window(0, 0, anchor="nw", window=self.frame)

  def update_scroll(self):
    "Need to update idletasks and bbox after gridding widgets into the frame"
    self.update_idletasks()
    self.config(scrollregion=self.bbox("all"))


class Data(object):
  _fname = ".pymol_lore.sqlite3"

  def __init__(self):
    self.fname = os.path.join(os.path.expanduser('~'), self._fname)
    self.conn = sqlite3.connect(
      self.fname, detect_types=sqlite3.PARSE_DECLTYPES)
    self.conn.row_factory = sqlite3.Row
    self.conn.isolation_level = None

    # Register python2sqlite3 and sqlite32python converters using json
    sqlite3.register_adapter(list, self._adapt_list)
    sqlite3.register_converter("list", self._convert_list)

    self._init_tables()

    self.current_results_keys = dict(user_fields_sha1="", fixed_fields_sha1="")
    self.current_target = dict(user_fields_sha1="", fixed_fields_sha1="")


  def _init_tables(self):
    self.uf_tbl = UserFieldsTable(self.conn)
    self.ff_tbl = FixedFieldsTable(self.conn)
    self.searchable = Searchable(self.conn)


  def add_target_def(self, pymol_selection, fixed_fields):
    "Add fields used to define the target to the table, indexed by ff_sha1"

    self.ff_tbl.store_row((
      fixed_fields["fixed_fields_sha1"],
      pymol_selection,
      fixed_fields["pdbname"],
      fixed_fields["residue_txt"],
    ))

  def add_search_params(self, user_fields):
    self.uf_tbl.store_row(user_fields)

  def update_searchable(self, rows):
    self.searchable.clear()
    self.searchable.store_many_rows(rows)

  def set_current_results_keys(self, user_fields_sha1="", fixed_fields_sha1=""):
    self.current_results_keys = dict(
      user_fields_sha1=user_fields_sha1, fixed_fields_sha1=fixed_fields_sha1)
    
  def searchable_records(self):
    return self.searchable.records()

  def _adapt_list(self, l):
    return json.dumps(l)

  def _convert_list(self, s):
    return json.loads(s)


class Controller(MainThreadConsumer):
  
  def __init__(self, app, 
               LoreURL="http://drugsite-dev.msi.umn.edu/mmLore/jsonrpc"):
    MainThreadConsumer.__init__(self, root=app.root)
    self.LoreURL = LoreURL
    self.rpc_server = jsonrpclib.Server(LoreURL)
    self.data = Data()
    self.update_searchable_subsets()
    self.app = app
    self.window = MainWindow(
      app.root, searchable=self.data.searchable_records())
    self.pages = self.window.notebook.pages

    self.pages["Define Target"].set_on_define_button_pushed_cb(
      self.on_define_structure_button_pushed)
    self.pages["Adjust Target"].set_on_search_button_pushed_cb(
      self.on_search_button_pushed)

    self.methods = {
      "search_metadata": self.update_search_metadata,
      "matches": self.update_search_results,
    }


  def on_define_structure_button_pushed(self, *args, **kwargs):
    if("widget" in kwargs):
      _brutally_set_state(kwargs["widget"], state='disabled')

    vars = dict([ (k, v.get()) for k,v in kwargs.get("vars", {}).iteritems() ])
    try:
      self.define_target_substructure(**vars)
    except jsonrpclib.jsonrpc.ProtocolError as E:
      _jsonrpc_exception_dialog(E)
    except Exception as E:
      tkMessageBox.showerror(
        title="Error", message="; ".join([ "%s" % (s) for s in E.args ]))
      # easier to debug during development if we raise the exception
      raise
    else:
      self.window.notebook.select(1)

    if("widget" in kwargs):
      _brutally_set_state(kwargs["widget"], state='normal')


  def on_search_button_pushed(self, *args, **kwargs):
    if("widget" in kwargs):
      _brutally_set_state(kwargs["widget"], state='disabled')

    vars = dict([ (k, v.get()) for k,v in kwargs.get("vars", {}).iteritems() ])
    try:
      self.do_search(**vars)
    except jsonrpclib.jsonrpc.ProtocolError as E:
      _jsonrpc_exception_dialog(E)
    except Exception as E:
      tkMessageBox.showerror(
        title="Error", message="; ".join([ "%s" % (s) for s in E.args ]))
      # easier to debug during development if we raise the exception
      raise
    else:
      self.window.notebook.select(2)

    if("widget" in kwargs):
      _brutally_set_state(kwargs["widget"], state='normal')


  def define_target_substructure(self, **kwargs):
    pymol_selection = kwargs.get("pymol_selection", "")
    target_pdbname = kwargs.get("target_pdbname", "")
    residue_txt = kwargs.get("residue_txt", "")

    if(pymol_selection):
      # verify that we have a valid pymol selection -- could be tricky if 
      # we want to give users warnings about select structures that are
      # neither amino acids or nucleic acids.
      raise NotImplementedError("This needs to be implemented!")
      (target_pdbname, residue_txt) = ("", "")
    elif(not target_pdbname and not residue_txt):
      msg = "You must provide either a PyMOL selection or a DrugSite"
      raise LoreException(msg + " selection")

    user_fields = self.rpc_server.define_target(
      pdbname=target_pdbname, residue_txt=residue_txt)
    self.data.add_target_def(pymol_selection, user_fields)
    my_page = self.pages["Adjust Target"]
    self.set_adjust_target_entries(pymol_selection, target_pdbname, residue_txt)
    self.update_adjust_target_match_filters(my_page, user_fields)
    self.update_adjust_target_match_params(my_page, user_fields)
    my_page.update_residue_filters_frame(user_fields)
    my_page.update_scroll()


  def do_search(self, **kwargs):
    data = {} 
    data["probe_pdblist"] = "|".join(kwargs.get("probe_pdblist", "").split())
    for f in ["superposition_atoms", "na_superposition_atoms"]:
      data[f] = "|".join(kwargs[f].split())

    (mask, resfilter) = ([], [])
    for r in kwargs["residues"].split("|"):
      resfilter.append(kwargs[r + "_filter"])
      mask.append(str(int(kwargs.get(r + "_mask", 1))))
    data["acceptable_residues"] = "|".join(resfilter)
    data["mask"] = "|".join(mask)

    data.update(dict(seg_pattern="", seg_joins=[]))
    for i in range(kwargs["num_segs"]):
      if(kwargs.get("seg_%d_joins_prev" % (i), 0) == 1):
        data["seg_joins"].append(True)
      else: data["seg_joins"].append(False)
  
      my_key = "seg_pattern_%d" % (i)
      if(len(kwargs[my_key]) != 1):
        msg = "Segment pattern %d must have exactly 1 character as input"
        raise ValueError(msg % (i))
      else: data["seg_pattern"] += kwargs[my_key]

    for k in ["best_match_only", "bestsequence", "ignore_seg_pattern"]:
      if(kwargs.get(k, 0) == 1): data[k] = True
      else: data[k] = False

    var_names = ["superposition_atoms", "na_superposition_atoms", ]
    for v in var_names:
      data[v] = "|".join(kwargs[v].split())

    var_names = ["intra_tolerance", "inter_tolerance", "na_intra_tolerance", 
                 "na_inter_tolerance", "rmslimit", ]
    for v in var_names:
      data[v] = float(kwargs[v])

    data["searchabletablename"] = kwargs["searchabletablename"]
    data["searchable_id"] = 0
    data["fixed_fields_sha1"] = kwargs["fixed_fields_sha1"]
    ovly_keys = self.rpc_server.set_user_fields(**data)

    data.update(ovly_keys)
    data["date_created"] = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())
    self.data.add_search_params(data)

    # submit search
    rv = self.rpc_server.request_search(**ovly_keys)
    self.data.set_current_results_keys(**ovly_keys)
    self.update_search_metadata(response=dict(search_is_pending=1))


  def set_adjust_target_entries(self, pymol_selection, target_pdbname,
                                residue_txt):
    self.pages["Adjust Target"].target_def.update(
      pymol_selection, target_pdbname, residue_txt)


  def update_adjust_target_search_types(self, page, user_fields):
    pass


  def update_adjust_target_match_filters(self, page, user_fields):
    for k in ["bestsequence", "best_match_only"]:
      page.vars[k].set(user_fields[k])


  def update_adjust_target_match_params(self, page, user_fields):
    var_names = [
      "superposition_atoms", "na_superposition_atoms", "intra_tolerance", 
      "inter_tolerance", "na_intra_tolerance", "na_inter_tolerance",
      "rmslimit",
    ]
    for k in var_names:
      page.vars[k].set(" ".join(str(user_fields[k]).split("|")))


  def update_searchable_subsets(self):
    subsets = self.rpc_server.get_searchable_subsets()
    # yea!, have to swap order
    tmp = [ (s[1], s[0]) for s in subsets ]
    self.data.update_searchable(tmp)


  def update_search_metadata(self, response={}):
    self.pages["Search Results"].set_search_status(**response)
    if(response.get("search_is_pending", 0) == 0): 
      self.request_search_results()
      return

    uf_sha1 = self.data.current_results_keys["user_fields_sha1"]
    t = JSONRPCThread(
      rpc_server=self.rpc_server, methodname="search_metadata", 
      queue=self.queue, kwargs=dict(user_fields_sha1=uf_sha1)
    )
    self.root.after(2000, t.start)


  def request_search_results(self, user_fields_sha1=""):
    if(not user_fields_sha1):
      user_fields_sha1 = self.data.current_results_keys["user_fields_sha1"]
    t = JSONRPCThread(
      rpc_server=self.rpc_server, methodname="matches", 
      queue=self.queue, kwargs=dict(user_fields_sha1=user_fields_sha1)
    )
    t.start()


  def update_search_results(self, response={}):
    self.pages["Search Results"].update_search_results(response["result"])
    for r in response["result"]:
      print r
    self.pages["Search Results"].update_scroll()


class MainWindow(Tkinter.Toplevel):
  _Toplevel_kw = {
    "borderwidth": "2",
  }
  _title = "Lore Substructure Searching"
  _geometry = "600x480+200+200"

  def __init__(self, master, cnf={}, **kw):
    self.searchable = kw.pop("searchable")
    for k,v in self._Toplevel_kw.iteritems():
      if(not k in kw):
        kw[k] = v
       
    Tkinter.Toplevel.__init__(self, master, cnf=cnf, **kw)
    self.title(self._title)
    self.geometry(self._geometry)
    self.notebook = Notebook(self)
    self.notebook.grid(row=0, column=0, sticky="news")
    ttk.Sizegrip(self).grid(row=1, column=1, sticky=("S","E"))


class TabFrame(ttk.Frame):
  _padding = (7,7)

  def __init__(self, master=None, **kw):
    ttk.Frame.__init__(self, master=master, **kw)
    self["padding"] = self._padding

    master.grid_rowconfigure(0, weight=1)
    master.grid_columnconfigure(0, weight=1)

    self._scrolling_frame = ScrollingFrame(self, yscroll=True)
    self._scrolling_frame.grid(row=0, column=0, sticky="news")
    self.inner_frame = self._scrolling_frame.frame

  def update_scroll(self):
    self._scrolling_frame.update_scroll()


  def Labelcheckbutton(self, master, label="", varname="", val=False):
    my_label = ttk.Label(master, text=label)
    self.vars[varname] = Tkinter.BooleanVar()
    self.vars[varname].set(val)
    vartxt = "On"
    if(val is False):
      vartxt = "Off"
    self.xboxes[varname] = ttk.Checkbutton(
      master, variable=self.vars[varname], text=vartxt,
      command=lambda var=varname: self._xbox_cb(var))
    return (my_label, self.xboxes[varname])


  def Entry(self, master, varname="", val="", width=20):
    self.vars[varname] = Tkinter.StringVar()
    self.vars[varname].set(val)
    return ttk.Entry(master, textvariable=self.vars[varname], width=width)


  def Labelentry(self, master, varname="", val="", width=20, label=""):
    entry = self.Entry(master, varname, val, width)
    return (ttk.Label(master, text=label), entry)


  def _xbox_cb(self, box_name):
    if(self.vars[box_name].get()):
      self.xboxes[box_name].configure(text="On")
    else:
      self.xboxes[box_name].configure(text="Off")




class DefineFrame(TabFrame):
  __entry_field_labels = {
    "pymol_selection": "PyMOL Selection:",
    "target_pdbname": "Lore PDB Name:",
    "residue_txt": "Lore Target Residues:",
  }
  __pymol_selection_txt = """
Use a PyMOL selection to
define a target substructure
"""
  __lore_selection_txt = """
Use a DrugSite selection to
define a target substructure
"""
  __balloons_text = {
    "pymol_selection": __pymol_selection_txt,
    "target_pdbname": __lore_selection_txt,
  }

  def __init__(self, master=None, **kw):
    TabFrame.__init__(self, master=master, **kw)

    self.vars = {}
    rowno=0
    for (k, v) in self.__entry_field_labels.iteritems():
      (my_label, my_entry) = self.Labelentry(
        self.inner_frame, varname=k, label=v)
      my_label.grid(row=rowno, column=0, sticky="w", padx=2, pady=2)
      my_entry.grid(row=rowno, column=1, padx=2, pady=2, sticky="we")
      rowno += 1
    self.define_button = ttk.Button(self.inner_frame, text="Define Target")
    self.define_button.grid(row=rowno, column=1, padx=5, pady=5)
    self.inner_frame.columnconfigure(1, weight=1)


  def set_on_define_button_pushed_cb(self, cb):
    self.define_button.configure(
      command=lambda s=self: cb(widget=s, vars=s.vars))


class AdjustFrame(TabFrame):

  def __init__(self, master=None, **kw):
    self.searchable = master.searchable
    TabFrame.__init__(self, master=master, **kw)
    self.vars = {}
  
    self.target_def = DisplayTargetDef(
      self.inner_frame, text="Target Substructure Definition")
    search_types = self._setup_search_types_frame()
    filter_types = self._setup_filter_types_frame()
    match_params = self._setup_match_parameters_frame()
    self.residue_filters = self._setup_residue_filters_frame()
    self.search_button = ttk.Button(self.inner_frame, text="Search")

    self.target_def.grid(row=0, column=0, padx=5, pady=5, sticky="W")
    search_types.grid(row=1, column=0, padx=5, pady=5, sticky="W")
    filter_types.grid(row=2, column=0, padx=5, pady=5, sticky="W")
    match_params.grid(row=3, column=0, padx=5, pady=5, sticky="W")
    self.residue_filters.grid(row=4, column=0, padx=5, pady=5, sticky="W")
    self.search_button.grid(row=5, column=0, padx=5, pady=5, sticky="W")


  def _setup_search_types_frame(self):
    frame = ttk.Labelframe(self.inner_frame, text="Search Types")
    frame["padding"] = (5,5)

    labs = [ ttk.Label(frame, text="List of Lore Structure Names:") ]
    labs.append( ttk.Label(frame, text="Lore Structures Subset:") )

    self.vars["probe_pdblist"] = Tkinter.StringVar()
    self.vars["searchabletablename"] = Tkinter.StringVar()

    entries = [ ttk.Entry(frame, textvariable=self.vars["probe_pdblist"]) ]
    entries[0].configure(width=30)
    entries.append( 
      ttk.Combobox(frame, textvariable=self.vars["searchabletablename"]) )
    entries[1]["values"] = [ row["name"] for row in self.searchable ]
    self.vars["searchabletablename"].set("All")

    for i in range(2):
      labs[i].grid(row=i, column=0, padx=2, pady=2, sticky="w")
      entries[i].grid(row=i, column=1, padx=2, pady=2, sticky="w")

    return frame


  def _setup_match_parameters_frame(self):
    var_names = [
      "superposition_atoms", "na_superposition_atoms",
      "intra_tolerance", "inter_tolerance",
      "na_intra_tolerance", "na_inter_tolerance",
      "rmslimit",
    ]
    labels = [
      "AA Superposition Atoms:", "NA Superposition Atoms:",
      "AA Intra Tolerance:", "AA Inter Tolerance:",
      "NA Intra Tolerance:", "NA Inter Tolerance:",
      "RMSD Tolerance:",
    ]
    desc = [
      "Atoms used to superimpose matched amino acids",
      "Atoms used to superimpose matched nucleic acids",
      "Maximum DG-error allowed within a bonded amino acid segment",
      "Maximum DG-error allowed between two bonded amino acid segments",
      "Maximum DG-error allowed within a bonded nucleic acid segment",
      "Maximum DG-error allowed between two bonded nucleic acid segments",
      "Maximum RMSD allowed for superposition of all matched atoms",
    ]  

    return self._setup_match_params("Match Parameters", labels, var_names, desc)


  def _setup_match_params(self, frame_label, labels, var_names, desc, 
                          padding=(5,5)):
    frame = ttk.Labelframe(self.inner_frame, text=frame_label)
    frame["padding"] = padding

    for i in range(len(labels)):
      my_row = self.Labelentry(
        frame, varname=var_names[i], label=labels[i], width=30)
      my_row += (ttk.Label(frame, text=desc[i]),)

      for j,el in enumerate(my_row):
        el.grid(row=i, column=j, padx=2, pady=2, sticky='W')

    return frame


  def update_residue_filters_frame(
    self, user_fields, padding=(5,5), 
    grid_opts=dict(row=4, column=0, padx=5, pady=5, sticky="W")):
    "The residue filters will change if target changes..."

    new_frame = self._setup_residue_filters_frame(user_fields, padding)
    self.residue_filters.grid_forget()
    self.residue_filters.destroy()
    new_frame.grid(**grid_opts)
    self.residue_filters = new_frame


  def _setup_residue_filters_frame(self, user_fields={}, padding=(5,5)):
    frame = ttk.Labelframe(self.inner_frame, text="Residue Filters")
    frame["padding"] = padding
    if(not user_fields): 
      return frame

    self.vars["residues"] = Tkinter.StringVar()
    self.vars["residues"].set(user_fields["residues"])
    self.vars["num_segs"] = Tkinter.IntVar()
    self.vars["num_segs"].set(len(user_fields["seg_lengths"]))
    self.vars["fixed_fields_sha1"] = Tkinter.StringVar()
    self.vars["fixed_fields_sha1"].set(user_fields["fixed_fields_sha1"])

    #ignore segment pattern
    (my_label, my_box) = self.Labelcheckbutton(
      frame, label="Ignore Segment Pattern", varname="ignore_seg_pattern",
      val=user_fields["ignore_seg_pattern"])
    my_label.grid(row=0, column=0, padx=5, pady=2, sticky="W")
    my_box.grid(row=0, column=1, padx=5, pady=2, sticky="W")

    residues = user_fields["residues"].split("|")
    acc_res = user_fields["acceptable_residues"].split("|")
    mask = [ bool(int(s)) for s in user_fields["mask"].split("|") ]
    seg_start = 0
    for seg_idx, seg_len in enumerate(user_fields["seg_lengths"]):
      res_frame = ttk.Labelframe(frame, text="Residue Segment %s" % (seg_idx))
    
      seg_stuff = self.Labelentry(
        res_frame, varname="seg_pattern_%s" % (seg_idx), width=2,
        label="Segment Pattern", val=user_fields["seg_pattern"][seg_idx])
      if(seg_idx > 0):
        seg_stuff += self.Labelcheckbutton(
          res_frame, label="Segment joins previous",
          varname="seg_%s_joins_prev" % (seg_idx),
          val=user_fields["seg_joins"][seg_idx])
      for j, s in enumerate(seg_stuff):
        s.grid(row=0, column=j+1, padx=5, pady=2, sticky="W")

      # header
      headings = ["Residue Name", "Respect Residue Distance Geometry",
                  "Acceptable Amino/Nucleic Acids"]
      col_span = [1, 2, 2]
      column = 0
      for j, h in enumerate(headings):
        head = ttk.Label(res_frame, text=h)
        head.grid(row=1, column=column, padx=5, pady=2, sticky="W",
                  columnspan=col_span[j])
        column += col_span[j]
   
      # rows
      rowno = 2
      for res_idx in range(seg_start, seg_start + seg_len):
        (reslabel, mask_box) = self.Labelcheckbutton(
          res_frame, label=residues[res_idx], 
          varname=(residues[res_idx] + "_mask"), val=mask[res_idx])
        entry = self.Entry(res_frame, varname=residues[res_idx] + "_filter",
                           val=acc_res[res_idx], width=26)
        
        reslabel.grid(row=rowno, column=0, padx=5, pady=2, sticky="W")
        mask_box.grid(row=rowno, column=1, padx=5, pady=2, sticky="W",
                      columnspan=2)
        entry.grid(row=rowno, column=3, padx=5, pady=2, sticky="W",
                   columnspan=2)

        rowno += 1
      
      res_frame.grid(row=seg_idx+1, column=0, padx=2, pady=3, sticky="W",
                     columnspan=2)
      seg_start += seg_len

    return frame


  def _setup_filter_types_frame(self):
    frame = ttk.Labelframe(self.inner_frame, text="Match Filters")
    frame["padding"] = (5,5)

    txt = [
      ["bestsequence", "Best Sequence:", "Keep best match for each sequence"],
      ["best_match_only", "Best Match:", 
       "Keep best match for each library structure"],
    ]
    self.xboxes = {}
    for (rowno, txt_tuple) in enumerate(txt):
      (row_label, row_box) = self.Labelcheckbutton(
        frame, label=txt_tuple[1], varname=txt_tuple[0])
      row_desc = ttk.Label(frame, text=txt_tuple[2])
      
      row_label.grid(row=rowno, column=0, sticky="W", padx=2, pady=2)
      row_box.grid(row=rowno, column=1, sticky="W", padx=2, pady=2)
      row_desc.grid(row=rowno, column=2, sticky="W", padx=2, pady=2)
    return frame


  def set_on_search_button_pushed_cb(self, cb):
    self.search_button.configure(
      command=lambda s=self: cb(widget=s, vars=s.vars))


class DisplayTargetDef(ttk.Labelframe):
  _labels_text = ["No target is defined;", "PyMOL Selection:",
                    "Lore PDB Name:", "Lore Residue Text:"]
  _padding = (5,5)

  def __init__(self, master=None, **kw):
    ttk.Labelframe.__init__(self, master=master, **kw)
    self["padding"] = self._padding

    self.labels = [ ttk.Label(self, text=l) for l in self._labels_text ]
    self.values = [ ttk.Label(self, text="") for l in self._labels_text ]
    self.values[0].configure(text="please define a target")
    self.labels[0].grid(row=0, sticky='w', padx=2, pady=2)
    self.values[0].grid(row=0, column=1, padx=2, pady=2)


  def update(self, pymol_selection="", target_pdbname="", residue_txt=""):
    for l in self.labels:
      l.grid_forget()
    for i in range(len(self.values)):
      self.values[i].grid_forget()

    if(pymol_selection):
      grid_idz = [1]
      self.values[1].configure(text=pymol_selection)
    elif(target_pdbname and residue_txt):
      grid_idz = [2, 3]
      self.values[2].configure(text=target_pdbname)
      self.values[3].configure(text=residue_txt.split("\n")[0])
    else:
      grid_idz = [0]

    for rowno, i in enumerate(grid_idz):
      self.labels[i].grid(row=rowno, sticky="W", padx=2, pady=2)
      self.values[i].grid(row=rowno, column=1, sticky="W", padx=2, pady=2)


class SearchResultsFrame(TabFrame):

  def __init__(self, master=None, **kw):
    self.searchable = master.searchable
    TabFrame.__init__(self, master=master, **kw)
    self.vars = {}

    search_status = self._setup_search_status_frame()
    self.search_results = None
    
    search_status.grid(row=0, column=0, sticky="W", padx=5, pady=5)


  def set_search_status(self, num_searched=0, num_probe_structs=0, 
                        search_is_pending=0, **kwargs):
    if(int(search_is_pending) == 1):
      if(num_searched == 0):
        self.search_status_label.configure(text="Search is pending")
      else:
        msg = "Searched %s of %s structures"
        self.search_status_label.configure(
          text=msg % (num_searched, num_probe_structs))
    else:
      self.search_status_label.configure(
        text="Searched a total of %s structures" % (num_searched))


  def update_search_results(self, search_results=[]):
    frame = self._setup_search_results_frame(search_results)

    if(self.search_results):
      self.search_results.grid_forget()
      self.search_results.destroy()
    self.search_results = frame
    self.search_results.grid(row=1, column=0, sticky="W", padx=5, pady=5)


  def _setup_search_status_frame(self, padding=(5,5)):
    frame = ttk.Labelframe(self.inner_frame, text="Search Status")
    frame["padding"] = padding
    self.search_status_label = ttk.Label(
      frame, text="No search is in progress, and no search was requested")
    self.search_status_label.grid(padx=2, pady=2, sticky="W")
    return frame


  def _setup_search_results_frame(self, search_results=[], padding=(5,5)):
    frame = ttk.Labelframe(self.inner_frame, text="Search Results")
    frame["padding"] = padding

    headings = ["RMSD", "Sequence\nScore", "Match\nName", "Aligned Segments"]
    if(search_results):
      for i, h in enumerate(headings):
        h = ttk.Label(frame, text=h)
        h.grid(row=0, column=i+1, padx=2, pady=2, sticky="W")

      for i,r in enumerate(search_results):
         # setup checkbox
         varname = "rowid_%s" % (r[0])
         self.vars[varname] = Tkinter.BooleanVar()
         self.vars[varname].set(False)
         my_row = (
           ttk.Checkbutton(frame, variable=self.vars[varname]), 
           ttk.Label(frame, text="%.2f" % (r[3])),
           ttk.Label(frame, text="%.2f" % (r[4])),
           ttk.Label(frame, text=r[2]),
         )
         for j,c in enumerate(my_row):
           c.grid(row=i+1, column=j, padx=2, pady=2, sticky="W")

    return frame





class Notebook(ttk.Notebook):
  _panel_borderwidth="2"
  _panel_relief="groove"

  _panels = [
    ("Define Target", DefineFrame),
    ("Adjust Target", AdjustFrame),
    ("Search Results", SearchResultsFrame),
  ]

  def __init__(self, master=None, **kw):
    ttk.Notebook.__init__(self, master=master, **kw)
    self.searchable = master.searchable

    _style = ttk.Style()
    _style.configure("Notebook.TFrame", borderwidth=self._panel_borderwidth,
                     relief=self._panel_relief)

    master.grid_rowconfigure(0, weight=1)
    master.grid_columnconfigure(0, weight=1)

    self.pages = {}
    #for (tag, klass) in self._panels.iteritems():
    for (tag, klass) in self._panels:
      self.pages[tag] = klass(self, style="Notebook.TFrame")
      self.add(self.pages[tag], text=tag)
      self.pages[tag].rowconfigure(0, weight=1)
      self.pages[tag].columnconfigure(0, weight=1)
      self.pages[tag].update_scroll()
