<xsl:stylesheet version="1.0" xmlns:xsl="http://www.w3.org/1999/XSL/Transform">
<xsl:output method="html" encoding="utf-8"
 doctype-system="http://www.w3.org/TR/html4/strict.dtd"
 doctype-public="-//W3C//DTD HTML 4.01//EN"/>
 <xsl:template match="TiVoContainer">
  <xsl:variable name="tivos" select="Tivos"/>
  <html>
   <head>
   <title>pyTivo - Push -
    <xsl:value-of select="Details/Title"/>
   </title>
   <link rel="stylesheet" type="text/css" href="/main.css"/>
   </head>
   <body>
   <form action="/TiVoConnect" method="POST">
    <p id="titlep"><span id="title">pyTivo - Push -
    <xsl:value-of select="Details/Title"/>
    </span></p>
	<p><a href="/">Home</a></p>
	<script language="JavaScript">
	<![CDATA[
	<!--
	function toggle(source) {
		var checkboxes = document.getElementsByName('File');
		for (var i = 0; i < checkboxes.length; i++) {
			if (typeof(checkboxes[i].checked) != "undefined") {
				checkboxes[i].checked = source.checked;
				}
		}
	}
	//-->
	]]>
	</script>
    <table id="main" style="text-align: left;" border="0" cellpadding="0" 
     cellspacing="4" width="100%">
	   <tr class="header">
		<td><input type="checkbox" name="selectAll" OnClick="toggle(this)" Title="Select All" /></td>
		<td></td>
		<td>Title</td>
		<td>Size</td>
		<td>Capture Date</td>
	   </tr>
       <tr id="parentLinkRow" style="display: none;">
        <td><img src="/back.png" alt="" /></td>
        <td width="100%" colspan="4">
        <a id="parentLink" href="">Up to Parent Folder</a>
        </td>
       </tr>
		<SCRIPT LANGUAGE="JavaScript">
	   	<![CDATA[
		<!--
		var sGet = window.location.search
		var re = new RegExp("([\?|&]Container=)(.*)/[^&]+", "g");
		var m = re.exec(sGet);
		if (m != null) {
			var re = new RegExp("([\?|&]Container=)(.*)/[^&]+", "g");
			sGet = sGet.replace(re, "$1$2");

			//Show up to parent folder link if we are in a subfolder
			document.getElementById('parentLink').href = sGet;
			document.getElementById('parentLinkRow').style.display = '';
		}
		//-->
		]]>
		</SCRIPT>
      <xsl:for-each select="Item">
       <tr>
       <xsl:choose>
        <xsl:when test="position() mod 2 = 1">
         <xsl:attribute name="class">
          <xsl:value-of select="'row1'"/>
         </xsl:attribute>
        </xsl:when>
        <xsl:otherwise>
         <xsl:attribute name="class">
          <xsl:value-of select="'row0'"/>
         </xsl:attribute>
        </xsl:otherwise>
       </xsl:choose>
       <xsl:choose>
        <xsl:when test="Details/ContentType = 'x-container/folder'">
          <td/>
          <td><img src="/folder.png" alt="" /></td>
          <td width="100%">
           <a>
            <xsl:attribute name="href">
             <xsl:value-of select="Links/Content/Url"/>
            </xsl:attribute>
            <xsl:value-of select="Details/Title"/>
           </a>
          </td>
          <td class="unbreak">
           <xsl:value-of select="Details/TotalItems"/> Items
          </td>
          <td class="unbreak"><xsl:value-of select="Links/Push/Date"/></td>
        </xsl:when>
        <xsl:otherwise>
          <td>
           <input type="checkbox" name="File">
            <xsl:attribute name="value">
             <xsl:value-of select="Links/Push/File"/>
            </xsl:attribute>
           </input>
          </td>
          <td/>
          <td width="100%">
           <span class="progtitle">
           <xsl:value-of select="Details/Title"/>
           <xsl:if test="Details/EpisodeTitle != ''">
            <xsl:if test="Details/EpisodeTitle != Details/Title">
             : <xsl:value-of select="Details/EpisodeTitle"/>
            </xsl:if>
           </xsl:if>
           </span>
           <xsl:if test="Details/Description != ''">
            <span class="progdesc">
            <xsl:value-of select="Details/Description"/>
            </span>
           </xsl:if>
          </td>
          <td class="unbreak">
           <xsl:value-of select="Links/Push/Size"/>
          </td>
          <td class="unbreak"><xsl:value-of select="Links/Push/Date"/></td>
        </xsl:otherwise>
       </xsl:choose>
       </tr>
      </xsl:for-each>
    </table>
    <p>
      <input type="hidden" name="Command" value="Push"/>
      <input type="hidden" name="Container">
       <xsl:attribute name="value">
        <xsl:value-of select="/TiVoContainer/Details/Title"/>
       </xsl:attribute>
      </input>
      <select name="tsn">
       <xsl:for-each select="/TiVoContainer/Tivos/Tivo">
        <option>
         <xsl:attribute name="value">
          <xsl:value-of select="."/>
         </xsl:attribute>
         <xsl:value-of select="."/>
        </option>
       </xsl:for-each>
      </select>
      <input value="Send to TiVo" type="submit"/>
    </p>
   </form>
   </body>
  </html>
 </xsl:template>
</xsl:stylesheet>
