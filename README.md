DrugSite-PyMOL
==============

A PyMOL plugin that allows PyMOL to function as a client for macromolecular substructure searching.

Note: this is currently in pre-alpha stage.  Nothing is expected to work at 
this time.

This plugin requires that you either install the jsonrpclib package to your 
PyMOL ext/lib/python2.7/site-packages directory or you use your system's python
and you will need to install the jsonrpclib package somewhere that your 
system's python can find it.  
Next copy the \_LoreSqlite.py and \_\_init\_\_.py files to your PyMOL ext/lib/python2.7/site-packages/LoreClient directory.
Finally, copy the LorePlugin.py file to your PyMOL modules/pmg_tk/startup
directory.
