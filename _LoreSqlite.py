import sqlite3

class BaseTable(object):

  def __init__(self, con):
    self.made_table = False
    self.con = con

    row = self.con.execute(
      """SELECT name, sql FROM sqlite_master 
         WHERE type = 'table' AND name = '%s'""" % (self.name)
    ).fetchone()

    cmd = "CREATE TABLE '%s'(\n\t%s %s" % \
      (self.name, self.fields[0][0], self.fields[0][1])
    for field in self.fields[1:]: cmd += ",\n\t%s %s" % (field[0], field[1])
    cmd += ")"
               
    # this check assumes that if one adds fields to the table, the added
    # fields will be appended to the existing list of fields.
    create_table = False
    if(row is not None and cmd != row["sql"]):
      create_table = True
      
    if(row is None or create_table):
      if(create_table): self.con.execute("DROP TABLE '%s'" % (self.name))
      self.con.execute(cmd)
      self.made_table = True

    self.insert_cmd = None


  def clear(self, rm_ids=[]):
    """
    Clear all records in the table subject to the remove ids.
    We don't want an unsantized where clause.
    """
    if(rm_ids):
      sql = "DELETE FROM '%s' WHERE ID IN (%s)" % \
        (self.name, ",".join(["?" for i in rm_ids]))
      self.con.execute(sql, tuple(rm_ids))
    else:
      self.con.execute("DELETE FROM '%s'" % (self.name,))

    # if we clear the entire table, we should be fine with reseting
    # autoincrement back to zero.
    if("AUTOINCREMENT" in self.fields[0][1]):
      cur = self.con.execute("SELECT COUNT(*), MAX(id) from '%s'" % (self.name))
      (count, max_id) = cur.fetchone()
      if(count <= 0): max_id = 1
      self.con.execute("UPDATE sqlite_sequence SET seq=? WHERE NAME=?",
                       (max_id, self.name)) 
    self.con.commit()


  def clear_by(self, **kwargs):
    for del_field in kwargs.keys():
      if(del_field in [ f[0] for f in self.fields ]):
        sql = "DELETE from '%s' where %s=?" % (self.name, del_field)
        self.con.execute(sql, (kwargs.get(del_field), ))
        self.con.commit()
        return True
      break
    return False


  def store_row(self, data):
    """
    Store a record from either a dictionary or a tuple

    :param data: a dictionary containing the fields for one row OR
                 a tuple representing a new row
    """
    if(self.insert_cmd is None): self._setup_insert_cmd()
    if(isinstance(data, (dict,))):
      tmp = tuple([ data.get(col) for (col, type) in self.fields[1:] ])
    elif(not isinstance(data, (tuple,))):
      raise ResultStoreError("Data for store_row must be a tuple or dictionary")
    else: 
      tmp = data

    rowid = self.con.execute(self.insert_cmd, tmp).lastrowid
    self.con.commit()
    return rowid


  def store_many_rows(self, rows):
    """
    Store a number of records

    :param rows: a list of class instances OR a list of tuples
    """
    if(not rows): return
    if(self.insert_cmd is None): self._setup_insert_cmd()
    tmp = rows
    if(not isinstance(rows[0], (tuple))):
      tmp = [ tuple([ r.__dict__.get(col, "") for (col, t) in self.fields[1:] ])
              for r in rows ]
    self.con.executemany(self.insert_cmd, tmp)
    self.con.commit()


  def _setup_insert_cmd(self):
    self.insert_cmd = "INSERT OR REPLACE INTO '%s' (%s)" % \
      (self.name, ",".join([ f[0] for f in self.fields]))
    self.insert_cmd += " values (%s)" % \
      (",".join([ "?" for i in range(len(self.fields)) ]))


  @property
  def counts(self):
    """
    Get the number of records for this table and the max value of the primary
    key for these records.  In this case, the primary key is the
    pdb_id of the pdbstore table.
    """
    cur = self.con.execute("SELECT count(*), max(id) from '%s'" % (self.name))
    return cur.fetchone()


  def getById(self, id):
    """
    Get a record by id.
    """
    cmd = "SELECT * from '%s' WHERE id=?" % (self.name)
    return self.con.execute(cmd, (int(id), )).fetchone()


  def records(self, pagination=None, order_by_tag="", ids=[]):
    """
    Get one page of matches from this table.  Order the matches based on the 
    order by clause that is constructed from the HTML form arguments.
    """
    order_by = self.get_order_by(order_by_tag)
   
    if(pagination is None):
      if(ids):
        sql = "SELECT * FROM '%s' WHERE id IN (%s) %s" % \
          (self.name, ",".join(["?" for id in ids]), order_by)
        args = tuple(ids)
      else:  
        sql = "SELECT * FROM '%s' %s" % (self.name, order_by)
        args = ()
    else:
      sql = "SELECT * FROM '%s' %s LIMIT ?, ?" % (self.name, order_by)
      args = (pagination.row_start, pagination.per_page)
    return self.con.execute(sql, args).fetchall()

  
  def get_order_by(self, order_by_tag):
    """
    Get an order by clause based on an html tag name (i.e. a string)
    """
    if(order_by_tag == ""): return ""

    tmp = order_by_tag.lower()
    if(tmp[-4:] == "_asc"): (field, order) = (order_by_tag[:-4], " ASC")
    elif(tmp[-4:] == "_dsc"): (field, order) = (order_by_tag[:-4], " DESC")
    else: (field, order) = (order_by_tag, "")

    return "\nORDER BY %s%s" % (field, order)

class FixedFieldsTable(BaseTable):

  def __init__(self, con):
    self.name = "fixed_fields"
    self.fields = (("fixed_fields_sha1", "TEXT PRIMARY KEY"),
                   ("pymol_selection", "TEXT"),
                   ("target_pdbname", "TEXT"),
                   ("residue_txt", "TEXT"),
#                   ("seg_lengths" ==> Need array converter <==),
#                   ("seg_polytypes", "TEXT"),
#                   ("overlay_id", "INTEGER"), 
#                   ("residues", "TEXT"),
#                   ("seg_mapping", "list"),
                  )
    BaseTable.__init__(self, con)


class UserFieldsTable(BaseTable):

  def __init__(self, con):
    self.name = "user_fields"
    self.fields = (("user_fields_sha1", "TEXT PRIMARY KEY"),
                   ("fixed_fields_sha1", "TEXT"),
#                   ("name", "TEXT"),
#                   ("description", "TEXT"),
                   ("inter_tolerance", "REAL"),
                   ("intra_tolerance", "REAL"),
                   ("na_inter_tolerance", "REAL"),
                   ("na_intra_tolerance", "REAL"),
                   ("mask", "TEXT"),
                   ("acceptable_residues", "TEXT"),
                   ("superposition_atoms", "TEXT"),
                   ("na_superposition_atoms", "TEXT"),
                   ("date_created", "TEXT"),
                   ("searchabletablename", "TEXT"),
#                   ("overlay_type", "TEXT"),
                   ("rmslimit", "REAL"),
                   ("bestsequence", "INTEGER"),
                   ("best_match_only", "INTEGER"),
                   ("seg_joins", "TEXT"),
                   ("seg_pattern", "TEXT"),
                   ("ignore_seg_pattern", "INTEGER"),
                   ("probe_pdblist", "TEXT"),
                  )
    BaseTable.__init__(self, con)


class Searchable(BaseTable):

  def __init__(self, con):
    self.name = "searchable"
    self.fields = (("id", "INTEGER PRIMARY KEY"),
                   ("name", "TEXT"),
                  )
    BaseTable.__init__(self, con)
