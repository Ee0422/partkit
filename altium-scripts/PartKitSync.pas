{ ==========================================================================
  PartKit Sync - runs inside Altium Designer.

  Reads the job file PartKit writes (partkit-data\sync\pending-sync.txt) and:
    * copies each approved symbol and footprint into the .SchLib/.PcbLib
      you chose, or draws the generic resistor/capacitor symbol;
    * creates the generic chip footprints (0402/0603/0805) with pads,
      silkscreen, courtyard and a 3D body;
    * writes every parameter (Manufacturer, MPN, Supplier...) onto the symbol
      and sets Comment to the value, so the BOM is clean;
    * places a separate .step model on the footprint, or adds a simple 3D
      box when the download had no model;
    * installs the libraries in Altium so they appear in Components;
    * writes sync-result.txt so PartKit knows what succeeded.

  Run: File > Run Script > PartKitSync.PrjScr > Run
  (PartKit will start this automatically in a later version.)

  STATUS: written against the Altium DelphiScript API but NOT yet tested in
  Altium. Please try it in Test mode first and report any error message.
  ========================================================================== }

var
  Root      : String;
  Results   : TStringList;
  TouchedSch: TStringList;
  TouchedPcb: TStringList;

{ ---------------- small helpers ---------------- }

function AbsPath(Rel : String) : String;
begin
  Rel := StringReplace(Rel, '/', '\', MkSet(rfReplaceAll));
  if (Length(Rel) > 1) and ((Copy(Rel, 2, 1) = ':') or (Copy(Rel, 1, 2) = '\\')) then
    Result := Rel
  else
    Result := Root + '\' + Rel;
end;

function ToFloat(S : String) : Double;
begin
  S := Trim(S);
  if S = '' then begin Result := 0; Exit; end;
  S := StringReplace(S, '.', DecimalSeparator, MkSet(rfReplaceAll));
  Result := StrToFloat(S);
end;

function BlockValue(Block : TStringList; Key : String) : String;
var I : Integer; P : String;
begin
  Result := '';
  P := Key + '=';
  for I := 0 to Block.Count - 1 do
    if Copy(Block[I], 1, Length(P)) = P then
    begin
      Result := Copy(Block[I], Length(P) + 1, Length(Block[I]));
      Exit;
    end;
end;

function FindJob : String;
var Ptr : TStringList; PtrPath : String; Dlg : TOpenDialog;
begin
  Result := '';
  { PartKit writes the current job location here on Windows. }
  PtrPath := 'C:\ProgramData\PartKit\current-job.txt';
  if FileExists(PtrPath) then
  begin
    Ptr := TStringList.Create;
    Ptr.LoadFromFile(PtrPath);
    if (Ptr.Count > 0) and FileExists(Trim(Ptr[0])) then Result := Trim(Ptr[0]);
    Ptr.Free;
  end;
  if Result = '' then
  begin
    Dlg := TOpenDialog.Create(nil);
    Dlg.Title := 'PartKit: choose pending-sync.txt';
    Dlg.Filter := 'PartKit sync job|pending-sync.txt';
    if Dlg.Execute then Result := Dlg.FileName;
    Dlg.Free;
  end;
end;

procedure Remember(List : TStringList; Path : String);
begin
  if List.IndexOf(Path) < 0 then List.Add(Path);
end;

procedure SaveDocument(Path : String);
var Doc : IServerDocument;
begin
  Doc := Client.GetDocumentByPath(Path);
  if Doc <> nil then Doc.DoFileSave('');
end;

{ ---------------- schematic library ---------------- }

function OpenSchLib(Path : String) : ISch_Lib;
var Doc : IServerDocument;
begin
  Result := nil;
  if not FileExists(Path) then
  begin
    ForceDirectories(ExtractFilePath(Path));
    Doc := CreateNewDocumentFromDocumentKind('SCHLIB');
    if Doc = nil then Exit;
    Doc.DoSafeChangeFileNameAndSave(Path, 'SCHLIB');
  end;
  Doc := Client.OpenDocument('SCHLIB', Path);
  if Doc = nil then Exit;
  Client.ShowDocument(Doc);
  Result := SchServer.GetSchDocumentByPath(Path);
end;

function FindSchComponent(Lib : ISch_Lib; Name : String) : ISch_Component;
var It : ISch_Iterator; C : ISch_Component;
begin
  Result := nil;
  It := Lib.SchLibIterator_Create;
  It.AddFilter_ObjectSet(MkSet(eSchComponent));
  C := It.FirstSchObject;
  while C <> nil do
  begin
    if SameText(C.LibReference, Name) then begin Result := C; Break; end;
    C := It.NextSchObject;
  end;
  Lib.SchIterator_Destroy(It);
end;

procedure AddPin(Comp : ISch_Component; X, Y, Len : Integer; Orient : Integer; Num : String);
var Pin : ISch_Pin;
begin
  Pin := SchServer.SchObjectFactory(ePin, eCreate_Default);
  Pin.Location := Point(MilsToCoord(X), MilsToCoord(Y));
  Pin.Orientation := Orient;
  Pin.PinLength := MilsToCoord(Len);
  Pin.Designator := Num;
  Pin.Name := Num;
  Pin.ShowName := False;
  Pin.ShowDesignator := False;
  Pin.Electrical := eElectricPassive;
  Pin.OwnerPartId := Comp.CurrentPartID;
  Pin.OwnerPartDisplayMode := Comp.DisplayMode;
  Comp.AddSchObject(Pin);
end;

procedure AddLine(Comp : ISch_Component; X1, Y1, X2, Y2 : Integer);
var L : ISch_Line;
begin
  L := SchServer.SchObjectFactory(eLine, eCreate_Default);
  L.Location := Point(MilsToCoord(X1), MilsToCoord(Y1));
  L.Corner := Point(MilsToCoord(X2), MilsToCoord(Y2));
  L.LineWidth := eMedium;
  L.OwnerPartId := Comp.CurrentPartID;
  L.OwnerPartDisplayMode := Comp.DisplayMode;
  Comp.AddSchObject(L);
end;

function NewGenericSymbol(Lib : ISch_Lib; Name, Kind : String) : ISch_Component;
var C : ISch_Component; R : ISch_Rectangle;
begin
  C := SchServer.SchObjectFactory(eSchComponent, eCreate_Default);
  C.CurrentPartID := 1;
  C.DisplayMode := 0;
  C.LibReference := Name;
  if Kind = 'R' then
  begin
    C.Designator.Text := 'R?';
    R := SchServer.SchObjectFactory(eRectangle, eCreate_Default);
    R.Location := Point(MilsToCoord(-100), MilsToCoord(-30));
    R.Corner := Point(MilsToCoord(100), MilsToCoord(30));
    R.IsSolid := False;
    R.OwnerPartId := C.CurrentPartID;
    R.OwnerPartDisplayMode := C.DisplayMode;
    C.AddSchObject(R);
    AddPin(C, -100, 0, 100, eRotate180, '1');
    AddPin(C, 100, 0, 100, eRotate0, '2');
  end
  else
  begin
    C.Designator.Text := 'C?';
    AddLine(C, -20, -60, -20, 60);
    AddLine(C, 20, -60, 20, 60);
    AddPin(C, -20, 0, 180, eRotate180, '1');
    AddPin(C, 20, 0, 180, eRotate0, '2');
  end;
  Lib.AddSchComponent(C);
  Result := C;
end;

function CopySymbol(SrcPath, SrcName : String; Dst : ISch_Lib; NewName : String) : ISch_Component;
var Src : ISch_Lib; C, N : ISch_Component;
begin
  Result := nil;
  Src := OpenSchLib(SrcPath);
  if Src = nil then Exit;
  C := FindSchComponent(Src, SrcName);
  if C = nil then Exit;
  N := C.Replicate;
  N.LibReference := NewName;
  Dst.AddSchComponent(N);
  Result := N;
end;

procedure SetParameter(Comp : ISch_Component; Name, Value : String);
var It : ISch_Iterator; P : ISch_Parameter;
begin
  It := Comp.SchIterator_Create;
  It.AddFilter_ObjectSet(MkSet(eParameter));
  P := It.FirstSchObject;
  while P <> nil do
  begin
    if SameText(P.Name, Name) then Break;
    P := It.NextSchObject;
  end;
  Comp.SchIterator_Destroy(It);
  if P = nil then
  begin
    P := SchServer.SchObjectFactory(eParameter, eCreate_Default);
    P.Name := Name;
    P.IsHidden := True;
    P.OwnerPartId := 0;
    Comp.AddSchObject(P);
  end;
  P.Text := Value;
end;

procedure ApplyParameters(Comp : ISch_Component; Block : TStringList);
var I, Bar : Integer; Line, Body : String;
begin
  for I := 0 to Block.Count - 1 do
  begin
    Line := Block[I];
    if Copy(Line, 1, 6) = 'PARAM=' then
    begin
      Body := Copy(Line, 7, Length(Line));
      Bar := Pos('|', Body);
      if Bar > 1 then
        SetParameter(Comp, Copy(Body, 1, Bar - 1), Copy(Body, Bar + 1, Length(Body)));
    end;
  end;
  Comp.Comment.Text := BlockValue(Block, 'COMMENT');
  Comp.ComponentDescription := BlockValue(Block, 'DESCRIPTION');
end;

procedure LinkFootprint(Comp : ISch_Component; FpName, PcbLibPath : String);
var It : ISch_Iterator; Impl : ISch_Implementation; Old : TList; I : Integer;
begin
  { remove vendor links, which may point at a file that no longer exists }
  Old := TList.Create;
  It := Comp.SchIterator_Create;
  It.AddFilter_ObjectSet(MkSet(eImplementation));
  Impl := It.FirstSchObject;
  while Impl <> nil do
  begin
    if SameText(Impl.ModelType, 'PCBLIB') then Old.Add(Impl);
    Impl := It.NextSchObject;
  end;
  Comp.SchIterator_Destroy(It);
  for I := 0 to Old.Count - 1 do Comp.RemoveSchImplementation(Old[I]);
  Old.Free;

  Impl := Comp.AddSchImplementation;
  Impl.ModelName := FpName;
  Impl.ModelType := 'PCBLIB';
  Impl.IsCurrent := True;
  Impl.AddDataFileLink(FpName, PcbLibPath, 'PCBLIB');
end;

{ ---------------- PCB library ---------------- }

function OpenPcbLib(Path : String) : IPCB_Library;
var Doc : IServerDocument;
begin
  Result := nil;
  if not FileExists(Path) then
  begin
    ForceDirectories(ExtractFilePath(Path));
    Doc := CreateNewDocumentFromDocumentKind('PCBLIB');
    if Doc = nil then Exit;
    Doc.DoSafeChangeFileNameAndSave(Path, 'PCBLIB');
  end;
  Doc := Client.OpenDocument('PCBLIB', Path);
  if Doc = nil then Exit;
  Client.ShowDocument(Doc);
  Result := PCBServer.GetPCBLibraryByPath(Path);
end;

function FindFootprint(Lib : IPCB_Library; Name : String) : IPCB_LibComponent;
var It : IPCB_LibraryIterator; F : IPCB_LibComponent;
begin
  Result := nil;
  It := Lib.LibraryIterator_Create;
  It.SetState_FilterAll;
  F := It.FirstPCBObject;
  while F <> nil do
  begin
    if SameText(F.Name, Name) then begin Result := F; Break; end;
    F := It.NextPCBObject;
  end;
  Lib.LibraryIterator_Destroy(It);
end;

function NewFootprint(Lib : IPCB_Library; Name : String) : IPCB_LibComponent;
begin
  Result := PCBServer.CreatePCBLibComp;
  Result.Name := Name;
  Lib.RegisterComponent(Result);
end;

procedure AddPrim(Fp : IPCB_LibComponent; Prim : IPCB_Primitive);
begin
  Fp.AddPCBObject(Prim);
  PCBServer.SendMessageToRobots(Fp.I_ObjectAddress, c_Broadcast, PCBM_BoardRegisteration, Prim.I_ObjectAddress);
end;

function CountBodies(Fp : IPCB_LibComponent) : Integer;
var It : IPCB_GroupIterator; P : IPCB_Primitive;
begin
  Result := 0;
  It := Fp.GroupIterator_Create;
  It.AddFilter_ObjectSet(MkSet(eComponentBodyObject));
  P := It.FirstPCBObject;
  while P <> nil do begin Inc(Result); P := It.NextPCBObject; end;
  Fp.GroupIterator_Destroy(It);
end;

function CopyFootprint(SrcPath, SrcName : String; Dst : IPCB_Library) : IPCB_LibComponent;
var Src : IPCB_Library; F, N : IPCB_LibComponent; It : IPCB_GroupIterator; P : IPCB_Primitive;
begin
  Result := nil;
  Src := OpenPcbLib(SrcPath);
  if Src = nil then Exit;
  F := FindFootprint(Src, SrcName);
  if F = nil then Exit;
  PCBServer.PreProcess;
  N := NewFootprint(Dst, SrcName);
  N.Height := F.Height;
  N.Description := F.Description;
  It := F.GroupIterator_Create;
  It.AddFilter_ObjectSet(AllObjects);
  P := It.FirstPCBObject;
  while P <> nil do
  begin
    AddPrim(N, P.Replicate);
    P := It.NextPCBObject;
  end;
  F.GroupIterator_Destroy(It);
  PCBServer.PostProcess;
  Result := N;
end;

procedure AddTrack(Fp : IPCB_LibComponent; X1, Y1, X2, Y2, W : Double; Layer : TLayer);
var T : IPCB_Track;
begin
  T := PCBServer.PCBObjectFactory(eTrackObject, eNoDimension, eCreate_Default);
  T.X1 := MMsToCoord(X1); T.Y1 := MMsToCoord(Y1);
  T.X2 := MMsToCoord(X2); T.Y2 := MMsToCoord(Y2);
  T.Width := MMsToCoord(W);
  T.Layer := Layer;
  AddPrim(Fp, T);
end;

procedure AddBox(Fp : IPCB_LibComponent; L, W, H : Double);
var B : IPCB_ComponentBody; C : IPCB_Contour;
begin
  if (L <= 0) or (W <= 0) then Exit;
  if H <= 0 then H := 1.0;
  B := PCBServer.PCBObjectFactory(eComponentBodyObject, eNoDimension, eCreate_Default);
  C := PCBServer.PCBContourFactory;
  C.AddPoint(MMsToCoord(-L / 2), MMsToCoord(-W / 2));
  C.AddPoint(MMsToCoord( L / 2), MMsToCoord(-W / 2));
  C.AddPoint(MMsToCoord( L / 2), MMsToCoord( W / 2));
  C.AddPoint(MMsToCoord(-L / 2), MMsToCoord( W / 2));
  B.SetOutlineContour(C);
  B.SetState_StandoffHeight(0);
  B.SetState_OverallHeight(MMsToCoord(H));
  B.BodyProjection := eBoardSide_Top;
  B.Layer := eMechanical13;
  AddPrim(Fp, B);
end;

function AddStep(Fp : IPCB_LibComponent; StepPath : String) : Boolean;
var B : IPCB_ComponentBody; M : IPCB_Model;
begin
  Result := False;
  if not FileExists(StepPath) then Exit;
  B := PCBServer.PCBObjectFactory(eComponentBodyObject, eNoDimension, eCreate_Default);
  M := B.ModelFactory_FromFilename(StepPath, False);
  if M = nil then Exit;
  B.SetState_FromModel;
  B.Model := M;
  B.Layer := eMechanical13;
  AddPrim(Fp, B);
  Result := True;
end;

procedure MakeChipFootprint(Block : TStringList);
var Lib : IPCB_Library; Fp : IPCB_LibComponent; Pad : IPCB_Pad;
    Name : String; PL, PW, PX, L, W, H, CX, CY : Double; I : Integer;
begin
  Name := BlockValue(Block, 'NAME');
  Lib := OpenPcbLib(AbsPath(BlockValue(Block, 'PCBLIB')));
  if Lib = nil then Exit;
  if FindFootprint(Lib, Name) <> nil then Exit;  { already made }
  PL := ToFloat(BlockValue(Block, 'PAD_L_MM'));
  PW := ToFloat(BlockValue(Block, 'PAD_W_MM'));
  PX := ToFloat(BlockValue(Block, 'PAD_X_MM'));
  L := ToFloat(BlockValue(Block, 'LENGTH_MM'));
  W := ToFloat(BlockValue(Block, 'WIDTH_MM'));
  H := ToFloat(BlockValue(Block, 'HEIGHT_MM'));
  PCBServer.PreProcess;
  Fp := NewFootprint(Lib, Name);
  Fp.Height := MMsToCoord(H);
  Fp.Description := 'PartKit generic chip footprint, IPC-7351B nominal';
  for I := 1 to 2 do
  begin
    Pad := PCBServer.PCBObjectFactory(ePadObject, eNoDimension, eCreate_Default);
    Pad.Mode := ePadMode_Simple;
    Pad.Layer := eTopLayer;
    Pad.HoleSize := 0;
    Pad.TopShape := eRoundedRectangular;
    Pad.TopXSize := MMsToCoord(PL);
    Pad.TopYSize := MMsToCoord(PW);
    if I = 1 then Pad.X := MMsToCoord(-PX) else Pad.X := MMsToCoord(PX);
    Pad.Y := 0;
    Pad.Name := IntToStr(I);
    AddPrim(Fp, Pad);
  end;
  { courtyard: pads + 0.25 mm }
  CX := PX + PL / 2 + 0.25;
  CY := Max(PW, W) / 2 + 0.25;
  AddTrack(Fp, -CX, -CY,  CX, -CY, 0.05, eMechanical15);
  AddTrack(Fp,  CX, -CY,  CX,  CY, 0.05, eMechanical15);
  AddTrack(Fp,  CX,  CY, -CX,  CY, 0.05, eMechanical15);
  AddTrack(Fp, -CX,  CY, -CX, -CY, 0.05, eMechanical15);
  AddBox(Fp, L, W, H);
  PCBServer.PostProcess;
  Remember(TouchedPcb, AbsPath(BlockValue(Block, 'PCBLIB')));
end;

{ ---------------- one part ---------------- }

function SyncPart(Block : TStringList) : String;
var SchDst : ISch_Lib; PcbDst : IPCB_Library; Comp, Old : ISch_Component;
    Fp : IPCB_LibComponent; Name, FpName, Model, Box, DstSch, DstPcb, Kind : String;
    Parts : TStringList;
begin
  Result := '';
  Name := BlockValue(Block, 'COMPONENT_NAME');
  FpName := BlockValue(Block, 'SRC_FOOTPRINT');
  DstSch := AbsPath(BlockValue(Block, 'DST_SCHLIB'));
  DstPcb := AbsPath(BlockValue(Block, 'DST_PCBLIB'));
  Model := BlockValue(Block, 'MODEL3D');

  { footprint first, so the symbol can link to it }
  PcbDst := OpenPcbLib(DstPcb);
  if PcbDst = nil then begin Result := 'could not open ' + DstPcb; Exit; end;
  Fp := FindFootprint(PcbDst, FpName);
  if (Fp = nil) and (BlockValue(Block, 'GENERIC') <> '1') then
  begin
    Fp := CopyFootprint(AbsPath(BlockValue(Block, 'SRC_PCBLIB')), FpName, PcbDst);
    if Fp = nil then begin Result := 'footprint ' + FpName + ' not found'; Exit; end;
    if (Model = 'external') and (CountBodies(Fp) = 0) then
    begin
      if not AddStep(Fp, AbsPath(BlockValue(Block, 'STEP'))) then
        Result := 'footprint copied but the 3D model could not be placed';
    end
    else if (Model = 'embedded') and (CountBodies(Fp) = 0) then
    begin
      { the embedded model did not copy across; use PartKit's .step copy }
      AddStep(Fp, AbsPath(BlockValue(Block, 'STEP')));
    end
    else if Model = 'box' then
    begin
      Box := BlockValue(Block, 'BOX_MM');
      if Box <> '' then
      begin
        Parts := TStringList.Create;
        Parts.CommaText := Box;
        AddBox(Fp, ToFloat(Parts[0]), ToFloat(Parts[1]), ToFloat(Parts[2]));
        Parts.Free;
      end;
    end;
  end;
  if Fp = nil then begin Result := 'footprint ' + FpName + ' missing'; Exit; end;
  Remember(TouchedPcb, DstPcb);

  { symbol }
  SchDst := OpenSchLib(DstSch);
  if SchDst = nil then begin Result := 'could not open ' + DstSch; Exit; end;
  Old := FindSchComponent(SchDst, Name);
  if (Old <> nil) and (BlockValue(Block, 'STAGE') = 'Obsolete') then
    Comp := Old
  else
  begin
    if Old <> nil then SchDst.RemoveSchComponent(Old);
    if BlockValue(Block, 'GENERIC') = '1' then
    begin
      if BlockValue(Block, 'CATEGORY') = 'Resistors' then Kind := 'R' else Kind := 'C';
      Comp := NewGenericSymbol(SchDst, Name, Kind);
    end
    else
      Comp := CopySymbol(AbsPath(BlockValue(Block, 'SRC_SCHLIB')), BlockValue(Block, 'SRC_SYMBOL'), SchDst, Name);
  end;
  if Comp = nil then begin Result := 'symbol ' + BlockValue(Block, 'SRC_SYMBOL') + ' not found'; Exit; end;
  ApplyParameters(Comp, Block);
  LinkFootprint(Comp, FpName, DstPcb);
  Remember(TouchedSch, DstSch);
end;

procedure InstallLibraries;
var I, J : Integer; Path : String; Found : Boolean; All : TStringList;
begin
  All := TStringList.Create;
  All.AddStrings(TouchedSch);
  All.AddStrings(TouchedPcb);
  for I := 0 to All.Count - 1 do
  begin
    Path := All[I];
    Found := False;
    for J := 0 to IntegratedLibraryManager.InstalledLibraryCount - 1 do
      if SameText(IntegratedLibraryManager.InstalledLibraryPath(J), Path) then Found := True;
    if not Found then IntegratedLibraryManager.InstallLibrary(Path);
  end;
  All.Free;
end;

{ ---------------- entry point ---------------- }

procedure Run;
var JobPath, Line, Err, Mpn : String; Lines, Block : TStringList; I, Ok, Failed : Integer;
    InPart, InFp : Boolean;
begin
  JobPath := FindJob;
  if JobPath = '' then Exit;
  Lines := TStringList.Create;
  Lines.LoadFromFile(JobPath);
  Results := TStringList.Create;
  TouchedSch := TStringList.Create;
  TouchedPcb := TStringList.Create;
  Block := TStringList.Create;
  Root := ExtractFileDir(ExtractFileDir(ExtractFileDir(JobPath)));
  Ok := 0; Failed := 0; InPart := False; InFp := False;

  for I := 0 to Lines.Count - 1 do
  begin
    Line := Lines[I];
    if Copy(Line, 1, 13) = 'LIBRARY_ROOT=' then Root := Copy(Line, 14, Length(Line))
    else if Line = '[PART]' then begin Block.Clear; InPart := True; end
    else if Line = '[FOOTPRINT]' then begin Block.Clear; InFp := True; end
    else if Line = '[END]' then
    begin
      if InFp then MakeChipFootprint(Block);
      if InPart then
      begin
        Mpn := BlockValue(Block, 'MPN');
        Err := SyncPart(Block);
        if Err = '' then begin Results.Add('OK=' + Mpn); Inc(Ok); end
        else begin Results.Add('FAIL=' + Mpn + '|' + Err); Inc(Failed); end;
      end;
      InPart := False; InFp := False;
    end
    else if InPart or InFp then Block.Add(Line);
  end;

  for I := 0 to TouchedPcb.Count - 1 do SaveDocument(TouchedPcb[I]);
  for I := 0 to TouchedSch.Count - 1 do SaveDocument(TouchedSch[I]);
  InstallLibraries;

  Results.SaveToFile(Root + '\partkit-data\sync\sync-result.txt');
  ShowMessage('PartKit Sync finished: ' + IntToStr(Ok) + ' parts updated, ' + IntToStr(Failed) +
              ' failed. Open PartKit to see the details.');
  Lines.Free; Block.Free; Results.Free; TouchedSch.Free; TouchedPcb.Free;
end;
