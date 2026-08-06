"""文件解析测试：CSV / XLSX / XLS / PPTX + 分发逻辑。"""
import pytest
from backend.ingest.file_parser import parse_file, _rows_to_markdown_table


# ═══════════════════════════════════════════════════════════════
# _rows_to_markdown_table 单元测试
# ═══════════════════════════════════════════════════════════════

class TestRowsToMarkdownTable:

    def test_header_detected(self):
        """首行全部非空 → 识别为表头，输出含 --- 分隔行。"""
        rows = [["Name", "Age"], ["Alice", "30"], ["Bob", "25"]]
        md = _rows_to_markdown_table(rows)
        assert "| Name | Age |" in md
        assert "| --- | --- |" in md
        assert "| Alice | 30 |" in md
        assert "| Bob | 25 |" in md

    def test_no_header(self):
        """首行有空单元格 → 自动生成 Col1/Col2 占位表头。"""
        rows = [["Alice", ""], ["Bob", "25"]]
        md = _rows_to_markdown_table(rows)
        assert "| Col1 | Col2 |" in md
        assert "| Alice |  |" in md

    def test_empty_rows(self):
        """空输入返回空字符串。"""
        assert _rows_to_markdown_table([]) == ""
        assert _rows_to_markdown_table([[], []]) == ""

    def test_trailing_empty_trimmed(self):
        """尾随全空行被裁剪。"""
        rows = [["A", "B"], ["1", "2"], ["", ""]]
        md = _rows_to_markdown_table(rows)
        # 第三行应被裁剪，只输出两行数据（header + sep + data，无尾随换行）
        lines = md.split("\n")
        assert len(lines) == 3  # header + sep + 1 data row

    def test_pipe_escaped(self):
        """单元格内 | 被转义。"""
        rows = [["A|B", "C"]]
        md = _rows_to_markdown_table(rows)
        assert "A\\|B" in md

    def test_newline_replaced(self):
        """单元格内换行符被替换为空格。"""
        rows = [["Line1\nLine2"]]
        md = _rows_to_markdown_table(rows)
        assert "\n" not in md.split("|")[1]


# ═══════════════════════════════════════════════════════════════
# CSV 解析
# ═══════════════════════════════════════════════════════════════

class TestParseCsv:

    def test_basic_csv(self, tmp_path):
        """标准 CSV 含表头 → markdown 表格。"""
        f = tmp_path / "test.csv"
        f.write_text("Name,Age,City\nAlice,30,NYC\nBob,25,LA", encoding="utf-8")
        result = parse_file(str(f))
        assert "| Name | Age | City |" in result
        assert "| --- | --- | --- |" in result
        assert "| Alice | 30 | NYC |" in result

    def test_csv_no_header(self, tmp_path):
        """首行有空值 → 自动补 Col 占位表头。"""
        f = tmp_path / "test.csv"
        f.write_text(",30\nBob,25", encoding="utf-8")
        result = parse_file(str(f))
        assert "| Col1 | Col2 |" in result

    def test_csv_empty(self, tmp_path):
        """空 CSV 返回空字符串。"""
        f = tmp_path / "test.csv"
        f.write_text("", encoding="utf-8")
        result = parse_file(str(f))
        assert result == ""

    def test_csv_tab_delimited(self, tmp_path):
        """制表符分隔 CSV → Sniffer 自动检测。"""
        f = tmp_path / "test.csv"
        f.write_text("Name\tAge\nAlice\t30", encoding="utf-8")
        result = parse_file(str(f))
        assert "| Name | Age |" in result
        assert "| Alice | 30 |" in result

    def test_csv_semicolon_delimited(self, tmp_path):
        """分号分隔 CSV → Sniffer 自动检测。"""
        f = tmp_path / "test.csv"
        f.write_text("Name;Age\nAlice;30", encoding="utf-8")
        result = parse_file(str(f))
        assert "| Name | Age |" in result

    def test_csv_encoding_gbk(self, tmp_path):
        """GBK 编码 CSV 含中文 → 正确解码。"""
        f = tmp_path / "test.csv"
        f.write_bytes("姓名,年龄\n张三,28\n李四,35".encode("gbk"))
        result = parse_file(str(f))
        assert "张三" in result
        assert "李四" in result


# ═══════════════════════════════════════════════════════════════
# XLSX 解析
# ═══════════════════════════════════════════════════════════════

class TestParseXlsx:

    def test_single_sheet(self, tmp_path):
        """单工作表 → ## Sheet 分节 + markdown 表格。"""
        import openpyxl
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Sales"
        ws.append(["Product", "Q1", "Q2"])
        ws.append(["Widget", 100, 150])
        p = tmp_path / "test.xlsx"
        wb.save(str(p))
        wb.close()

        result = parse_file(str(p))
        assert "## Sheet: Sales" in result
        assert "| Product | Q1 | Q2 |" in result
        assert "| Widget | 100 | 150 |" in result

    def test_multiple_sheets(self, tmp_path):
        """多工作表 → 每个表独立分节。"""
        import openpyxl
        wb = openpyxl.Workbook()
        ws1 = wb.active
        ws1.title = "Q1"
        ws1.append(["A", "B"])
        ws2 = wb.create_sheet("Q2")
        ws2.append(["C", "D"])
        p = tmp_path / "test.xlsx"
        wb.save(str(p))
        wb.close()

        result = parse_file(str(p))
        assert "## Sheet: Q1" in result
        assert "## Sheet: Q2" in result

    def test_empty_sheet_skipped(self, tmp_path):
        """空工作表 → 不产生输出。"""
        import openpyxl
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Empty"
        # 不添加任何数据行
        p = tmp_path / "test.xlsx"
        wb.save(str(p))
        wb.close()

        result = parse_file(str(p))
        assert result == ""

    def test_formula_cells(self, tmp_path):
        """公式单元格 → data_only=True 读取计算结果。"""
        import openpyxl
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.append(["A", "B"])
        ws.append([10, 20])
        ws.append(["=A2+B2", None])  # 公式只存在于文件内，data_only 时读缓存值
        p = tmp_path / "test.xlsx"
        wb.save(str(p))
        wb.close()

        result = parse_file(str(p))
        assert "| A | B |" in result
        # 公式单元格值可能为 None（未计算时），但不应崩溃
        assert "|" in result  # 至少输出表格


# ═══════════════════════════════════════════════════════════════
# XLS 解析
# ═══════════════════════════════════════════════════════════════

class TestParseXls:

    def test_basic_xls(self, tmp_path):
        """标准 .xls → markdown 表格。"""
        import xlwt
        wb = xlwt.Workbook()
        ws = wb.add_sheet("Data")
        ws.write(0, 0, "Name")
        ws.write(0, 1, "Score")
        ws.write(1, 0, "Alice")
        ws.write(1, 1, 95)
        p = tmp_path / "test.xls"
        wb.save(str(p))

        result = parse_file(str(p))
        assert "## Sheet: Data" in result
        assert "| Name | Score |" in result
        assert "| Alice | 95.0 |" in result  # xlrd 数值统一返回 float

    def test_multiple_sheets_xls(self, tmp_path):
        """多工作表 .xls → 每个表独立分节。"""
        import xlwt
        wb = xlwt.Workbook()
        ws1 = wb.add_sheet("Sheet1")
        ws1.write(0, 0, "A")
        ws2 = wb.add_sheet("Sheet2")
        ws2.write(0, 0, "B")
        p = tmp_path / "test.xls"
        wb.save(str(p))

        result = parse_file(str(p))
        assert "## Sheet: Sheet1" in result
        assert "## Sheet: Sheet2" in result

    def test_empty_xls(self, tmp_path):
        """无数据行的 .xls 返回空。"""
        import xlwt
        wb = xlwt.Workbook()
        wb.add_sheet("Empty")
        p = tmp_path / "test.xls"
        wb.save(str(p))

        result = parse_file(str(p))
        assert result == ""


# ═══════════════════════════════════════════════════════════════
# PPTX 解析
# ═══════════════════════════════════════════════════════════════

class TestParsePptx:

    def test_slide_with_text(self, tmp_path):
        """含文本幻灯片 → ## Slide N + 文本内容。"""
        from pptx import Presentation
        prs = Presentation()
        slide = prs.slides.add_slide(prs.slide_layouts[1])
        slide.shapes.title.text = "Hello World"
        slide.placeholders[1].text = "This is body text"
        p = tmp_path / "test.pptx"
        prs.save(str(p))

        result = parse_file(str(p))
        assert "## Slide 1" in result
        assert "Hello World" in result
        assert "This is body text" in result

    def test_slide_with_table(self, tmp_path):
        """含表格幻灯片 → 内嵌 markdown 表格。"""
        from pptx import Presentation
        from pptx.util import Inches
        prs = Presentation()
        slide = prs.slides.add_slide(prs.slide_layouts[6])  # blank
        table_shape = slide.shapes.add_table(2, 2, Inches(1), Inches(1), Inches(6), Inches(3))
        table_shape.table.cell(0, 0).text = "A"
        table_shape.table.cell(0, 1).text = "B"
        table_shape.table.cell(1, 0).text = "1"
        table_shape.table.cell(1, 1).text = "2"
        p = tmp_path / "test.pptx"
        prs.save(str(p))

        result = parse_file(str(p))
        assert "## Slide 1" in result
        assert "| A | B |" in result
        assert "| 1 | 2 |" in result

    def test_multiple_slides(self, tmp_path):
        """多幻灯片 → 每页独立 ## Slide N 分节。"""
        from pptx import Presentation
        prs = Presentation()
        for i in range(3):
            slide = prs.slides.add_slide(prs.slide_layouts[1])
            slide.shapes.title.text = f"Slide {i+1}"
        p = tmp_path / "test.pptx"
        prs.save(str(p))

        result = parse_file(str(p))
        assert "## Slide 1" in result
        assert "## Slide 2" in result
        assert "## Slide 3" in result

    def test_empty_slide_skipped(self, tmp_path):
        """纯图片/无文本幻灯片 → 不产生输出。"""
        from pptx import Presentation
        prs = Presentation()
        prs.slides.add_slide(prs.slide_layouts[6])  # blank, no text
        p = tmp_path / "test.pptx"
        prs.save(str(p))

        result = parse_file(str(p))
        assert result == ""


# ═══════════════════════════════════════════════════════════════
# parse_file 分发逻辑
# ═══════════════════════════════════════════════════════════════

class TestParseFileDispatch:

    def test_unknown_extension(self, tmp_path):
        """不支持的扩展名 → ValueError。"""
        f = tmp_path / "test.xyz"
        f.write_text("content")
        with pytest.raises(ValueError, match="不支持的文件类型"):
            parse_file(str(f))

    def test_missing_file(self):
        """文件不存在 → FileNotFoundError。"""
        with pytest.raises(FileNotFoundError, match="文件不存在"):
            parse_file("/nonexistent/path/file.txt")

    def test_case_insensitive_extension(self, tmp_path):
        """扩展名大小写不敏感：.CSV / .Csv 均可识别。"""
        f = tmp_path / "test.CSV"
        f.write_text("Name,Age\nAlice,30", encoding="utf-8")
        result = parse_file(str(f))
        assert "| Name | Age |" in result

    def test_all_supported_formats_registered(self):
        """确认所有 11 种格式已在 _PARSERS + _OCR_FORMATS 注册。"""
        from backend.ingest.file_parser import _PARSERS, _OCR_FORMATS
        expected_parsers = {".txt", ".md", ".docx", ".csv", ".xlsx", ".xls", ".pptx"}
        expected_ocr = {".pdf", ".png", ".jpg", ".jpeg"}
        assert set(_PARSERS.keys()) == expected_parsers
        assert _OCR_FORMATS == expected_ocr
