"""Compile provided APK widget geometry and state tracks for browser preview."""
from pathlib import Path
import json

ROOT=Path(__file__).resolve().parent
BASE=ROOT.parent/'球员工坊/library/converted/PesMobile/Content/Assets/ui/Data/Widget/Parts/Components/Placeholders/UiPlayerCard/Core'

def build():
    documents={name:json.loads((BASE/(name+'.json')).read_text(encoding='utf-8-sig'))
               for name in ('PlayerCardFrontInfo','PlayerCardFrontInfoBooster')}
    result={'source':'provided APK PlayerCardFrontInfo + PlayerCardFrontInfoBooster',
            'width':268,'height':384,'widgets':{},'states':{}}
    for name,doc in documents.items():
        for export in doc:
            props=export.get('Properties',{})
            if export['Type']=='MovieScene':
                state={}
                for binding in props.get('ObjectBindings',[]):
                    obj=state.setdefault(binding['BindingName'],{})
                    for ref in binding.get('Tracks',[]):
                        track=doc[int(ref['ObjectPath'].rsplit('.',1)[1])]['Properties']
                        for section_ref in track.get('Sections',[]):
                            section=doc[int(section_ref['ObjectPath'].rsplit('.',1)[1])]['Properties']
                            if 'ByteCurve' in section:obj['visible']=section['ByteCurve']['Values'][0] in (0,3,4)
                            for key in ('Translation','Translation[1]','Scale','Scale[1]','Rotation'):
                                if key in section:obj[key]=section[key]['Values'][0]['Value']
                result['states'][export['Name']]=state
            if props.get('Slot') and export['Name'] in (
                    'Text_Overall','Text_Position','Text_Date',*[f'Text_PlayerName_{i}' for i in range(6)],
                    'EmblemClub','EmblemNationality','Img_eFootballLogo','ScaleBox_RarityStar',
                    'ScaleBox_IconCelebration','ScaleBox_IconCombi','ScaleBox_BoosterSlot_1','ScaleBox_BoosterSlot_2'):
                slot=doc[int(props['Slot']['ObjectPath'].rsplit('.',1)[1])]['Properties']['LayoutData']
                offset=slot['Offsets'];font=props.get('_font',{})
                result['widgets'][export['Name']]={
                    'x':offset.get('Left',0),'y':offset.get('Top',0),'w':offset.get('Right',0),'h':offset.get('Bottom',0),
                    'size':font.get('Size',23),'font':font.get('TypefaceFontName','Regular'),
                    'align':'center' if props.get('Justification')=='ETextJustify::Center' else 'left',
                    'angle':props.get('RenderTransform',{}).get('Angle',0),
                    'pivot':props.get('RenderTransformPivot',{'X':.5,'Y':.5}),
                    'visible':props.get('Visibility')!='ESlateVisibility::Collapsed'}
    # Native ARM64 function 0x3141e6c: isBigTime precedes CardKind switch.
    # CardKind jump table at 0xc3b9af is [63,43,82,74,0,0,43,0].
    result['native_dispatch']={'address':'0x3141e6c','kind_states':{
        'Standard':0,'Legendary':1,'GOAT':2,'Trending':3,'Featured':4,'Epic':1,'Highlight':4},
        'big_time':5,'trending_new_asset_threshold':340}
    paths=(ROOT.parent/'.work/game-assets/all-list.txt').read_text(encoding='utf-8-sig').splitlines()
    result['symbols']={}
    for path in paths:
        if path.startswith('PesMobile/') and path.endswith('.uasset') and '/ui/Data/Symbol/' in path:
            result['symbols'][Path(path).stem]=path
    result['graphics']={Path(path).stem:path for path in paths if path.startswith('PesMobile/') and path.endswith('.uasset') and
                        ('/UiPlayerCard/Tex720/' in path or '/CmnIconBooster/Tex720/' in path)}
    dest=ROOT/'resources/native-card-widgets.json'
    dest.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    return result

if __name__=='__main__':
    result=build();print(len(result['widgets']),'widgets',len(result['states']),'states')
