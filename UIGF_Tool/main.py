"""
UIGF 转换器 - 主程序
使用 maliang UI 库构建图形界面
"""

import json
import tkinter.filedialog as filedialog
import tkinter.messagebox as messagebox
from pathlib import Path
from typing import Optional, Type, List

import maliang

from converters import (
    BaseConverter,
    ConverterRegistry,
    detect_source_type,
    ConversionError
)


class UIGFConverterApp:
    """UIGF 转换器应用"""
    
    # 窗口大小
    WINDOW_WIDTH = 720
    WINDOW_HEIGHT = 500
    
    AUTO_DETECT_NAME = "自动检测"
    
    def __init__(self):
        """初始化应用"""
        self.root = maliang.Tk(
            size=(self.WINDOW_WIDTH, self.WINDOW_HEIGHT),
            title="UIGF 转换器"
        )
        self.root.center()
        
        # 状态
        self.input_file_path: Optional[Path] = None
        self.input_data: Optional[dict] = None
        self.detected_converter: Optional[Type[BaseConverter]] = None
        
        self._create_ui()
        
        self.root.center()
    
    def _create_ui(self):
        """创建用户界面"""
        # 画布
        self.canvas = maliang.Canvas(
            auto_zoom=True,
            keep_ratio="min",
            free_anchor=True
        )
        self.canvas.place(
            width=self.WINDOW_WIDTH,
            height=self.WINDOW_HEIGHT,
            x=self.WINDOW_WIDTH // 2,
            y=self.WINDOW_HEIGHT // 2,
            anchor="center"
        )
        
        maliang.Text(
            self.canvas,
            (self.WINDOW_WIDTH // 2, 50),
            text="UIGF 转换器",
            fontsize=32,
            anchor="center"
        )
        
        maliang.Text(
            self.canvas,
            (self.WINDOW_WIDTH // 2, 90),
            text="将各种来源的祈愿记录转换为标准 UIGF v4.1 格式",
            fontsize=12,
            anchor="center"
        )
        
        self._create_input_section()
        
        self._create_source_section()
        
        self._create_action_buttons()
        
        self._create_status_section()
    
    def _create_input_section(self):
        """创建输入文件选择区域"""
        maliang.Text(
            self.canvas,
            (40, 140),
            text="输入文件",
            fontsize=16,
            anchor="nw"
        )
        
        # 文件路径
        self.file_path_text = maliang.Text(
            self.canvas,
            (40, 170),
            text="请选择要转换的 JSON 文件...",
            fontsize=11,
            anchor="nw"
        )
        
        # 检测结果
        self.detect_result_text = maliang.Text(
            self.canvas,
            (40, 195),
            text="",
            fontsize=11,
            anchor="nw"
        )
        
        self.select_button = maliang.Button(
            self.canvas,
            (self.WINDOW_WIDTH - 140, 165),
            (100, 36),
            text="选择文件",
            command=self._on_select_file
        )
    
    def _create_source_section(self):
        """创建来源类型选择区域"""
        maliang.Text(
            self.canvas,
            (40, 240),
            text="来源类型",
            fontsize=16,
            anchor="nw"
        )
        
        # 获取来源选项列表
        self.source_options: List[str] = [self.AUTO_DETECT_NAME]
        self.source_options.extend(ConverterRegistry.get_display_names())
        
        self.source_option = maliang.OptionButton(
            self.canvas,
            (40, 270),
            (200, 36),
            text=tuple(self.source_options),
            command=self._on_source_changed
        )
        # 默认选择第一个（自动检测）
        self.source_option.set(0)
    
    def _on_source_changed(self, index: int):
        """来源类型改变回调（索引）"""
        pass  # 当前选择的索引已存储，无需额外处理
    
    def _get_source_display_name(self) -> str:
        """获取当前选择的来源显示名称"""
        try:
            index = self.source_option.get()
            if 0 <= index < len(self.source_options):
                return self.source_options[index]
        except Exception:
            pass
        return self.AUTO_DETECT_NAME
    
    def _set_source_by_name(self, display_name: str) -> bool:
        """根据显示名称设置来源选择"""
        try:
            index = self.source_options.index(display_name)
            self.source_option.set(index)
            return True
        except ValueError:
            return False
    
    def _create_action_buttons(self):
        """创建转换按钮"""
        self.convert_button = maliang.Button(
            self.canvas,
            (self.WINDOW_WIDTH // 2 - 60, 340),
            (120, 44),
            text="开始转换",
            command=self._on_convert
        )
    
    def _create_status_section(self):
        """创建状态显示区域"""
        maliang.Text(
            self.canvas,
            (40, 410),
            text="状态",
            fontsize=16,
            anchor="nw"
        )
        
        # 状态文本
        self.status_text = maliang.Text(
            self.canvas,
            (40, 440),
            text="等待操作...",
            fontsize=12,
            anchor="nw"
        )
    
    def _on_select_file(self):
        """选择文件回调"""
        file_path = filedialog.askopenfilename(
            title="选择要转换的 JSON 文件",
            filetypes=[
                ("JSON 文件", "*.json"),
                ("所有文件", "*.*")
            ]
        )
        
        if not file_path:
            return
        
        self.input_file_path = Path(file_path)

        self.file_path_text.set(f"已选择: {self.input_file_path.name}")

        try:
            with open(self.input_file_path, "r", encoding="utf-8") as f:
                self.input_data = json.load(f)
        except json.JSONDecodeError as e:
            self._update_status(f"错误: JSON 解析失败 - {str(e)}", error=True)
            return
        except Exception as e:
            self._update_status(f"错误: 无法读取文件 - {str(e)}", error=True)
            return
        
        # 自动检测来源
        self._detect_and_update()
    
    def _detect_and_update(self):
        """检测来源类型并更新界面"""
        if self.input_data is None:
            return
        
        # 自动检测
        self.detected_converter = detect_source_type(self.input_data)
        
        if self.detected_converter:
            self.detect_result_text.set(
                f"✓ 检测到: {self.detected_converter.get_display_name()}"
            )

            self._set_source_by_name(self.detected_converter.get_display_name())
        else:
            self.detect_result_text.set("⚠ 无法识别来源类型")
    
    def _get_selected_converter(self) -> Optional[Type[BaseConverter]]:
        """获取当前选择的转换器"""
        selected = self._get_source_display_name()
        
        if selected == self.AUTO_DETECT_NAME:
            return self.detected_converter
        
        # 根据显示名称获取转换器
        identifier = ConverterRegistry.get_identifier_by_display_name(selected)
        if identifier:
            return ConverterRegistry.get(identifier)
        
        return None
    
    def _on_convert(self):
        """转换按钮回调"""
        if self.input_data is None:
            messagebox.showwarning("提示", "请先选择要转换的文件")
            return
        
        # 获取转换器
        converter = self._get_selected_converter()
        if converter is None:
            messagebox.showwarning(
                "提示",
                "无法确定来源类型，请手动选择来源类型"
            )
            return
        
        # 选择输出文件
        output_path = filedialog.asksaveasfilename(
            title="保存转换结果",
            defaultextension=".json",
            initialfile=f"{self.input_file_path.stem}_converted.json",
            filetypes=[
                ("JSON 文件", "*.json"),
                ("所有文件", "*.*")
            ]
        )
        
        if not output_path:
            return
        
        output_path = Path(output_path)
        
        # 执行转换
        self._update_status("正在转换...")
        self.root.update()
        
        try:
            output_data = converter.convert(self.input_data)
            
            # 写入文件
            with open(output_path, "w", encoding="utf-8") as f:
                json.dump(output_data, f, ensure_ascii=False, indent=2)
            
            # 获取统计信息
            stats = self._get_conversion_stats(converter, output_data)
            
            self._update_status(
                f"转换成功! {stats}"
            )
            
            messagebox.showinfo(
                "成功",
                f"转换完成!\n\n输出文件: {output_path}\n\n{stats}"
            )
            
        except ConversionError as e:
            self._update_status(f"转换失败: {str(e)}", error=True)
            messagebox.showerror("错误", f"转换失败:\n{str(e)}")
        except Exception as e:
            self._update_status(f"错误: {str(e)}", error=True)
            messagebox.showerror("错误", f"发生错误:\n{str(e)}")
    
    def _get_conversion_stats(self, converter: Type[BaseConverter], output_data: dict) -> str:
        """获取转换统计信息字符串"""
        if hasattr(converter, "get_conversion_stats"):
            stats = converter.get_conversion_stats(self.input_data, output_data)
            return (
                f"共转换 {stats['output_items']} 条记录，"
                f"涉及 {stats['uid_count']} 个 UID"
            )
        
        # 默认统计
        hk4e = output_data.get("hk4e", [])
        total_items = sum(len(entry.get("list", [])) for entry in hk4e)
        uid_count = len(hk4e)
        
        return f"共转换 {total_items} 条记录，涉及 {uid_count} 个 UID"
    
    def _update_status(self, message: str, error: bool = False):
        """更新状态显示"""
        prefix = "❌ " if error else ""
        self.status_text.set(f"{prefix}{message}")
    
    def run(self):
        """运行应用"""
        self.root.mainloop()


def main():
    """主函数"""
    # 确保所有转换器都已注册
    from converters import HeyboxConverter  # noqa: F401
    
    # 创建并运行应用
    app = UIGFConverterApp()
    app.run()


if __name__ == "__main__":
    main()
