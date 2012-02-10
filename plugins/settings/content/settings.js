function fillBlank()
{
    var texts = document.getElementsByTagName('input');
    for (var i_tem = 0; i_tem < texts.length; i_tem++) {
        if (texts[i_tem].value == '') {
            texts[i_tem].value = ' ';
        }
    }
}

function switchDiv(pass, type)
{
    //loop through the array and hide/show each element by id
    var divs = document.getElementsByTagName('div');
    for (var i = 0; i < divs.length; i++) {
        if (divs[i].id.match(type)) {
            if (divs[i].id == pass) {
                divs[i].style.display = 'block'
            } else {
                divs[i].style.display = 'none'
            }
        }
    }
}

function deleteSection(id)
{
    var ss = document.getElementById('ss');
    var name = ss.section.options[id].text;
    if (name == 'Global Server Settings') {
        alert('Delete Error:\n\nSorry the Global Server Settings ' +
              'Section is required for pyTivo to run and cannot be deleted');
        return true;
    }
    var answer = confirm("Are you sure you wish to delete the '" + name +
                         "' Section?")
    if (answer) {
        switchDiv('set-delete', 'set-');
        ss.section.options[id] = null;
        var field = document.getElementById('opts.' + name).value;
        document.getElementById(field).value = 'Delete_Me';
        saveNotify();
        return true;
    }
}

function redir(target)
{
    var answer = confirm('Are you sure you wish to ' + target +
                         ' pyTivo? Any unsaved changes will be lost!')
    if (answer) {
        window.location = '/TiVoConnect?Command=' + target +
                          '&Container=Settings'
    }
}

function showData(form)
{
    var section = "";
    var setting = "";
    re = /[\[\]<>|]/;
    inputs = form.getElementsByTagName("input");
    for (i = 0; i < inputs.length; i++) {
        if (inputs[i].type == 'text' && re.exec(inputs[i].value)) {
            setting = inputs[i].name;
            break;
        }
    }
    if (setting != "") {
        var map = document.getElementById('Section_Map').value.split(']');
        map.pop();
        splitSetting = setting.split('.');
        for (i = 0; i < map.length; i++) {
            key = map[i].split('|');
            if (splitSetting[0] == 'Server') {
                section = 'server';
                break;
            }
            if (key[0] == splitSetting[0]) {
                section = key[1];
                break;
            }
        }
        alert("Invalid Entry:\nSorry these are not allowed \n[]<>|");
        switchDiv('set-' + section, 'set-');
        document.getElementById(setting).select();
        return false;
    }
    fillBlank();
    document.config.submit();
}

function saveNotify()
{
    document.getElementById('B1').style.fontWeight = 'bold';
    document.getElementById('B2').disabled = true;
}
